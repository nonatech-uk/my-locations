#!/usr/bin/env python3
"""Generate comprehensive location history report and email it."""

import json
import math
import smtplib
from collections import defaultdict
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

import db

GEOCODE_CACHE_FILE = Path(__file__).parent.parent / "data" / "geocode_cache.json"


def load_geocode_cache():
    """Load geocode cache from JSON file, or return empty dict if missing."""
    if GEOCODE_CACHE_FILE.exists():
        with open(GEOCODE_CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_geocode_cache(cache):
    """Write geocode cache to JSON file."""
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GEOCODE_CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def reverse_geocode_cached(lat, lon, cache):
    """Reverse geocode with cache. Returns (place, country) or None on failure."""
    key = f"{round(lat, 2)},{round(lon, 2)}"
    if key in cache:
        return cache[key]['place'], cache[key]['country']

    try:
        location = reverse(f'{lat}, {lon}', language='en', addressdetails=True)
        if location:
            addr = location.raw.get('address', {})
            place = (addr.get('village') or addr.get('town') or addr.get('city') or
                    addr.get('municipality') or addr.get('hamlet') or addr.get('suburb') or
                    addr.get('neighbourhood') or addr.get('county') or addr.get('state') or
                    'Unknown')
            country = addr.get('country', 'Unknown')

            if country in ['United Kingdom', 'England', 'Wales', 'Scotland', 'Northern Ireland']:
                country = 'United Kingdom'

            cache[key] = {'place': place, 'country': country}
            return place, country
    except Exception as e:
        print(f"Geocode error for ({lat}, {lon}): {e}")

    return None


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance between two points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Geocoder setup
geolocator = Nominatim(user_agent='mylocation-analysis')
reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1.1)


def get_clusters(limit=200):
    """Get location clusters from stationary/slow points."""
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute('''
        WITH stationary AS (
            SELECT id, lat, lon, geom::geometry as geom, ts,
                   EXTRACT(HOUR FROM ts) as hour,
                   DATE(ts) as visit_date
            FROM gps_points
            WHERE speed_mph IS NULL OR speed_mph <= 5
        ),
        clustered AS (
            SELECT
                ST_ClusterDBSCAN(geom, eps := 0.005, minpoints := 3) OVER() as cluster_id,
                lat, lon, ts, hour, visit_date
            FROM stationary
        ),
        daily_hours AS (
            SELECT
                cluster_id,
                visit_date,
                EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) / 3600.0 as hours_on_day
            FROM clustered
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id, visit_date
        )
        SELECT
            c.cluster_id,
            COUNT(*) as point_count,
            AVG(c.lat) as centroid_lat,
            AVG(c.lon) as centroid_lon,
            MIN(c.ts) as first_seen,
            MAX(c.ts) as last_seen,
            COUNT(*) FILTER (WHERE c.hour >= 23 OR c.hour <= 6) as night_points,
            array_agg(DISTINCT EXTRACT(YEAR FROM c.ts)::int ORDER BY EXTRACT(YEAR FROM c.ts)::int) as years,
            COUNT(DISTINCT DATE(c.ts)) as day_count,
            COALESCE((SELECT SUM(hours_on_day) FROM daily_hours dh WHERE dh.cluster_id = c.cluster_id), 0) as total_hours,
            array_agg(DISTINCT c.visit_date) FILTER (WHERE c.hour >= 23 OR c.hour <= 6) as night_dates
        FROM clustered c
        WHERE c.cluster_id IS NOT NULL
        GROUP BY c.cluster_id
        HAVING COALESCE((SELECT SUM(hours_on_day) FROM daily_hours dh WHERE dh.cluster_id = c.cluster_id), 0) >= 3
        ORDER BY day_count DESC
        LIMIT %s
    ''', (limit,))

    clusters = cur.fetchall()
    conn.close()
    return clusters


def get_overnight_stays():
    """Get overnight stays: where last point of day N is close to first point of day N+1."""
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute('''
        WITH daily_bounds AS (
            SELECT
                DATE(ts) as day,
                FIRST_VALUE(ts) OVER (PARTITION BY DATE(ts) ORDER BY ts) as first_ts,
                FIRST_VALUE(lat) OVER (PARTITION BY DATE(ts) ORDER BY ts) as first_lat,
                FIRST_VALUE(lon) OVER (PARTITION BY DATE(ts) ORDER BY ts) as first_lon,
                LAST_VALUE(ts) OVER (PARTITION BY DATE(ts) ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_ts,
                LAST_VALUE(lat) OVER (PARTITION BY DATE(ts) ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_lat,
                LAST_VALUE(lon) OVER (PARTITION BY DATE(ts) ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_lon
            FROM gps_points
            WHERE speed_mph IS NULL OR speed_mph <= 5
        )
        SELECT DISTINCT day, first_ts, first_lat, first_lon, last_ts, last_lat, last_lon
        FROM daily_bounds
        ORDER BY day
    ''')

    rows = cur.fetchall()
    conn.close()

    # Find overnight stays: last point of day N close to first point of day N+1
    overnights = []
    for i in range(len(rows) - 1):
        day1, _, _, _, last_ts, last_lat, last_lon = rows[i]
        day2, first_ts, first_lat, first_lon, _, _, _ = rows[i + 1]

        # Check if consecutive days
        if day2 - day1 != timedelta(days=1):
            continue

        dist = haversine_km(last_lat, last_lon, first_lat, first_lon)

        if dist < 1.0:  # Within 1km = overnight stay
            overnights.append({
                'date': day1,  # Night of this date
                'lat': (last_lat + first_lat) / 2,
                'lon': (last_lon + first_lon) / 2,
            })

    return overnights


def get_travel_days():
    """Get days where first point is >100km from the last point of the previous day."""
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute('''
        WITH daily_bounds AS (
            SELECT
                DATE(ts) as day,
                FIRST_VALUE(lat) OVER (PARTITION BY DATE(ts) ORDER BY ts) as first_lat,
                FIRST_VALUE(lon) OVER (PARTITION BY DATE(ts) ORDER BY ts) as first_lon,
                LAST_VALUE(lat) OVER (PARTITION BY DATE(ts) ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_lat,
                LAST_VALUE(lon) OVER (PARTITION BY DATE(ts) ORDER BY ts
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_lon
            FROM gps_points
            WHERE speed_mph IS NULL OR speed_mph <= 5
        )
        SELECT DISTINCT day, first_lat, first_lon, last_lat, last_lon
        FROM daily_bounds
        ORDER BY day
    ''')

    rows = cur.fetchall()
    conn.close()

    travel_days = []
    for i in range(len(rows) - 1):
        day1, _, _, last_lat, last_lon = rows[i]
        day2, first_lat, first_lon, _, _ = rows[i + 1]

        if day2 - day1 != timedelta(days=1):
            continue

        dist = haversine_km(last_lat, last_lon, first_lat, first_lon)

        if dist >= 100:
            travel_days.append({
                'date': day2,
                'from_lat': last_lat,
                'from_lon': last_lon,
                'to_lat': first_lat,
                'to_lon': first_lon,
                'distance_km': dist,
            })

    return travel_days


def geocode_travel_days(travel_days, cache):
    """Reverse geocode travel day endpoints and return structured data."""
    result = []
    cached, new = 0, 0

    for td in travel_days:
        from_cache_key = f"{round(td['from_lat'], 2)},{round(td['from_lon'], 2)}"
        from_was_cached = from_cache_key in cache
        from_result = reverse_geocode_cached(td['from_lat'], td['from_lon'], cache)

        to_cache_key = f"{round(td['to_lat'], 2)},{round(td['to_lon'], 2)}"
        to_was_cached = to_cache_key in cache
        to_result = reverse_geocode_cached(td['to_lat'], td['to_lon'], cache)

        if from_result and to_result:
            from_place, from_country = from_result
            to_place, to_country = to_result
            result.append({
                'date': td['date'],
                'from': f"{from_place}, {from_country}",
                'to': f"{to_place}, {to_country}",
                'distance_km': td['distance_km'],
            })
            cached += (1 if from_was_cached else 0) + (1 if to_was_cached else 0)
            new += (0 if from_was_cached else 1) + (0 if to_was_cached else 1)

    print(f"  Geocoding: {cached} cached, {new} new lookups")
    return result


def geocode_overnights(overnights, cache):
    """Reverse geocode overnight stays and aggregate by place."""
    # First, cluster overnights by rounded coordinates to reduce geocoding calls
    # Round to ~1km precision (0.01 degrees ≈ 1km)
    location_clusters = defaultdict(list)
    for stay in overnights:
        key = (round(stay['lat'], 2), round(stay['lon'], 2))
        location_clusters[key].append(stay['date'])

    print(f"  Clustered into {len(location_clusters)} unique locations")

    # Geocode each unique location once
    places = defaultdict(lambda: {
        'nights': set(),
        'country': ''
    })

    cached, new = 0, 0
    for (lat, lon), dates in location_clusters.items():
        cache_key = f"{round(lat, 2)},{round(lon, 2)}"
        was_cached = cache_key in cache
        result = reverse_geocode_cached(lat, lon, cache)
        if result:
            place, country = result
            key = f'{place}, {country}'
            places[key]['nights'].update(dates)
            places[key]['country'] = country
            if was_cached:
                cached += 1
            else:
                new += 1

    print(f"  Geocoding: {cached} cached, {new} new lookups")
    return places


def geocode_clusters(clusters, cache):
    """Reverse geocode clusters and aggregate by place."""
    places = defaultdict(lambda: {
        'points': 0,
        'first_seen': None,
        'last_seen': None,
        'night_points': 0,
        'night_dates': set(),
        'years': set(),
        'country': '',
        'days': 0,
        'hours': 0.0
    })

    cached, new = 0, 0
    for cluster in clusters:
        cluster_id, points, lat, lon, first_seen, last_seen, night_points, years, day_count, total_hours, night_dates = cluster
        cache_key = f"{round(lat, 2)},{round(lon, 2)}"
        was_cached = cache_key in cache
        result = reverse_geocode_cached(lat, lon, cache)
        if result:
            place, country = result
            key = f'{place}, {country}'

            places[key]['points'] += points
            places[key]['night_points'] += night_points
            if night_dates:
                places[key]['night_dates'].update(night_dates)
            places[key]['country'] = country
            places[key]['years'].update(years)
            places[key]['days'] += day_count
            places[key]['hours'] += float(total_hours)

            if places[key]['first_seen'] is None or first_seen < places[key]['first_seen']:
                places[key]['first_seen'] = first_seen
            if places[key]['last_seen'] is None or last_seen > places[key]['last_seen']:
                places[key]['last_seen'] = last_seen

            if was_cached:
                cached += 1
            else:
                new += 1

    print(f"  Geocoding: {cached} cached, {new} new lookups")
    return places


def generate_html_report(places, overnight_data, travel_days_data=None):
    """Generate HTML report."""
    sorted_places = sorted(places.items(), key=lambda x: x[1]['days'], reverse=True)

    # Aggregate by country
    countries = defaultdict(lambda: {'days': 0, 'places': []})
    for place, data in sorted_places:
        country = data['country']
        countries[country]['days'] += data['days']
        countries[country]['places'].append(place.split(',')[0])

    sorted_countries = sorted(countries.items(), key=lambda x: x[1]['days'], reverse=True)

    # Aggregate by year
    years = defaultdict(lambda: {'days': 0, 'places': set()})
    for place, data in sorted_places:
        for year in data['years']:
            years[year]['days'] += data['days'] // len(data['years'])  # Approximate
            years[year]['places'].add(place.split(',')[0])

    # Overnight stays from new logic (last point of day close to first point of next day)
    overnight_places = []
    for place, data in overnight_data.items():
        overnight_places.append((place, {
            'nights': len(data['nights']),
            'night_dates': data['nights'],
            'first_night': min(data['nights']) if data['nights'] else None,
            'last_night': max(data['nights']) if data['nights'] else None,
        }))
    overnight_places.sort(key=lambda x: x[1]['nights'], reverse=True)

    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; background: white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background: #4CAF50; color: white; padding: 12px 8px; text-align: left; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f9f9f9; }}
        .stat-box {{ display: inline-block; background: white; padding: 15px 25px; margin: 10px;
                    border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); text-align: center; }}
        .stat-number {{ font-size: 2em; font-weight: bold; color: #4CAF50; }}
        .stat-label {{ color: #666; font-size: 0.9em; }}
        .section {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px;
                   box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    </style>
</head>
<body>
    <h1>Location History Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

    <div style="text-align: center; margin: 30px 0;">
        <div class="stat-box">
            <div class="stat-number">{len(sorted_places)}</div>
            <div class="stat-label">Locations Visited</div>
        </div>
        <div class="stat-box">
            <div class="stat-number">{len(sorted_countries)}</div>
            <div class="stat-label">Countries</div>
        </div>
        <div class="stat-box">
            <div class="stat-number">{len(overnight_places)}</div>
            <div class="stat-label">Overnight Stays</div>
        </div>
        <div class="stat-box">
            <div class="stat-number">{len(travel_days_data) if travel_days_data else 0}</div>
            <div class="stat-label">Travel Days</div>
        </div>
        <div class="stat-box">
            <div class="stat-number">{max(years.keys()) - min(years.keys()) + 1}</div>
            <div class="stat-label">Years of Data</div>
        </div>
    </div>

    <div class="section">
    <h2>All Locations Ranked by Days Visited</h2>
    <table>
        <tr><th>#</th><th>Location</th><th>Days</th><th>First Visit</th><th>Last Visit</th></tr>
'''

    for i, (place, data) in enumerate(sorted_places, 1):
        first = str(data['first_seen'])[:10] if data['first_seen'] else '-'
        last = str(data['last_seen'])[:10] if data['last_seen'] else '-'
        html += f'        <tr><td>{i}</td><td>{place}</td><td>{data["days"]:,}</td><td>{first}</td><td>{last}</td></tr>\n'

    html += '''    </table>
    </div>

    <div class="section">
    <h2>Countries by Days Visited</h2>
    <table>
        <tr><th>#</th><th>Country</th><th>Days</th><th>Places Visited</th></tr>
'''

    for i, (country, data) in enumerate(sorted_countries, 1):
        places_str = ', '.join(data['places'][:8])
        if len(data['places']) > 8:
            places_str += f' (+{len(data["places"]) - 8} more)'
        html += f'        <tr><td>{i}</td><td>{country}</td><td>{data["days"]:,}</td><td>{places_str}</td></tr>\n'

    html += '''    </table>
    </div>
'''

    html += f'''    <div class="section">
    <h2>Overnight Stays</h2>
    <p><em>{len(overnight_places)} locations (last point of day within 1km of first point of next day)</em></p>
    <table>
        <tr><th>#</th><th>Location</th><th>Nights</th><th>First Stay</th><th>Last Stay</th></tr>
'''

    for i, (place, data) in enumerate(overnight_places[:50], 1):
        first = str(data['first_night']) if data['first_night'] else '-'
        last = str(data['last_night']) if data['last_night'] else '-'
        html += f'        <tr><td>{i}</td><td>{place}</td><td>{data["nights"]:,}</td><td>{first}</td><td>{last}</td></tr>\n'

    html += '''    </table>
    </div>

    <div class="section">
    <h2>Overnight Stays by Year</h2>
'''

    # Group overnight stays by year
    for year in sorted(years.keys(), reverse=True):
        # Calculate nights specifically in this year for each place
        year_overnight = []
        for p, d in overnight_places:
            nights_in_year = len([dt for dt in d['night_dates'] if dt.year == year])
            if nights_in_year > 0:
                year_overnight.append((p, nights_in_year))
        year_overnight.sort(key=lambda x: x[1], reverse=True)
        if year_overnight:
            html += f'    <h3>{year}</h3>\n'
            html += '    <table>\n'
            html += '        <tr><th>#</th><th>Location</th><th>Nights</th></tr>\n'
            for i, (place, nights) in enumerate(year_overnight[:10], 1):
                html += f'        <tr><td>{i}</td><td>{place}</td><td>{nights:,}</td></tr>\n'
            html += '    </table>\n'

    html += '''    </div>

    <div class="section">
    <h2>Yearly Travel Summary</h2>
    <table>
        <tr><th>Year</th><th>Places Visited</th></tr>
'''

    for year in sorted(years.keys()):
        places_list = sorted(years[year]['places'])
        places_str = ', '.join(places_list[:12])
        if len(places_list) > 12:
            places_str += f' (+{len(places_list) - 12} more)'
        html += f'        <tr><td><strong>{year}</strong></td><td>{places_str}</td></tr>\n'

    html += '''    </table>
    </div>
'''

    if travel_days_data:
        # Group travel days by year
        travel_by_year = defaultdict(list)
        for td in travel_days_data:
            travel_by_year[td['date'].year].append(td)

        total_travel = len(travel_days_data)
        html += f'''    <div class="section">
    <h2>Travel Days</h2>
    <p><em>{total_travel} days where first location was 100km+ from previous day's last location</em></p>
'''

        for year in sorted(travel_by_year.keys(), reverse=True):
            days = travel_by_year[year]
            html += f'    <h3>{year} ({len(days)} travel days)</h3>\n'
            html += '    <table>\n'
            html += '        <tr><th>Date</th><th>From</th><th>To</th><th>Distance</th></tr>\n'
            for td in sorted(days, key=lambda x: x['date']):
                html += (f'        <tr><td>{td["date"]}</td><td>{td["from"]}</td>'
                         f'<td>{td["to"]}</td><td>{td["distance_km"]:,.0f} km</td></tr>\n')
            html += '    </table>\n'

        html += '    </div>\n'

    html += '''
    <p style="color: #999; font-size: 0.8em; margin-top: 30px; text-align: center;">
        Generated from GPS data • Excludes transit (speed > 5 mph) • Clusters within ~500m combined
    </p>
</body>
</html>
'''
    return html


def send_email(html_content, to_email):
    """Send HTML email via local sendmail."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f' Location History Report - {datetime.now().strftime("%Y-%m-%d")}'
    msg['From'] = 'mylocation@mees.st'
    msg['To'] = to_email

    msg.attach(MIMEText(html_content, 'html'))

    # Try sendmail first, fall back to localhost SMTP
    try:
        import subprocess
        p = subprocess.Popen(['/usr/sbin/sendmail', '-t', '-oi'],
                           stdin=subprocess.PIPE)
        p.communicate(msg.as_bytes())
        if p.returncode == 0:
            return True
    except:
        pass

    # Fallback to SMTP
    try:
        with smtplib.SMTP('localhost') as server:
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


def main():
    cache = load_geocode_cache()
    print(f"Loaded geocode cache ({len(cache)} entries)")

    print("Fetching location clusters...")
    clusters = get_clusters(limit=200)
    print(f"Found {len(clusters)} clusters")

    print("Reverse geocoding clusters...")
    places = geocode_clusters(clusters, cache)
    print(f"Identified {len(places)} distinct locations")

    print("Fetching overnight stays...")
    overnights = get_overnight_stays()
    print(f"Found {len(overnights)} overnight stays")

    print("Reverse geocoding overnight stays...")
    overnight_data = geocode_overnights(overnights, cache)
    print(f"Identified {len(overnight_data)} overnight locations")

    print("Fetching travel days (>100km overnight moves)...")
    travel_days = get_travel_days()
    print(f"Found {len(travel_days)} travel days")

    print("Reverse geocoding travel days...")
    travel_days_data = geocode_travel_days(travel_days, cache)
    print(f"Geocoded {len(travel_days_data)} travel days")

    save_geocode_cache(cache)
    print(f"Saved geocode cache ({len(cache)} entries)")

    print("Generating HTML report...")
    html = generate_html_report(places, overnight_data, travel_days_data)

    # Save HTML to reports directory
    reports_dir = Path(__file__).parent.parent / "reports"
    report_path = reports_dir / "location_report.html"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Report saved to {report_path}")

    # Email
    print("Sending email to stu@mees.st...")
    if send_email(html, 'stu@mees.st'):
        print("Email sent successfully!")
    else:
        print("Email failed - check report file locally")


if __name__ == '__main__':
    main()
