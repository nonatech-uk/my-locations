#!/usr/bin/env python3
"""Generate comprehensive location history report and email it."""

import smtplib
from collections import defaultdict
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

import db

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
                   EXTRACT(HOUR FROM ts) as hour
            FROM gps_points
            WHERE speed_mph IS NULL OR speed_mph <= 5
        ),
        clustered AS (
            SELECT
                ST_ClusterDBSCAN(geom, eps := 0.005, minpoints := 3) OVER() as cluster_id,
                lat, lon, ts, hour
            FROM stationary
        )
        SELECT
            cluster_id,
            COUNT(*) as point_count,
            AVG(lat) as centroid_lat,
            AVG(lon) as centroid_lon,
            MIN(ts) as first_seen,
            MAX(ts) as last_seen,
            COUNT(*) FILTER (WHERE hour >= 23 OR hour <= 6) as night_points,
            array_agg(DISTINCT EXTRACT(YEAR FROM ts)::int ORDER BY EXTRACT(YEAR FROM ts)::int) as years
        FROM clustered
        WHERE cluster_id IS NOT NULL
        GROUP BY cluster_id
        ORDER BY point_count DESC
        LIMIT %s
    ''', (limit,))

    clusters = cur.fetchall()
    conn.close()
    return clusters


def geocode_clusters(clusters):
    """Reverse geocode clusters and aggregate by place."""
    places = defaultdict(lambda: {
        'points': 0,
        'first_seen': None,
        'last_seen': None,
        'night_points': 0,
        'years': set(),
        'country': ''
    })

    for cluster in clusters:
        cluster_id, points, lat, lon, first_seen, last_seen, night_points, years = cluster
        try:
            location = reverse(f'{lat}, {lon}', language='en', addressdetails=True)
            if location:
                addr = location.raw.get('address', {})
                place = (addr.get('village') or addr.get('town') or addr.get('city') or
                        addr.get('municipality') or 'Unknown')
                country = addr.get('country', 'Unknown')

                # Normalize UK
                if country in ['United Kingdom', 'England', 'Wales', 'Scotland', 'Northern Ireland']:
                    country = 'United Kingdom'

                key = f'{place}, {country}'

                places[key]['points'] += points
                places[key]['night_points'] += night_points
                places[key]['country'] = country
                places[key]['years'].update(years)

                if places[key]['first_seen'] is None or first_seen < places[key]['first_seen']:
                    places[key]['first_seen'] = first_seen
                if places[key]['last_seen'] is None or last_seen > places[key]['last_seen']:
                    places[key]['last_seen'] = last_seen
        except Exception as e:
            print(f"Geocode error for ({lat}, {lon}): {e}")

    return places


def generate_html_report(places):
    """Generate HTML report."""
    sorted_places = sorted(places.items(), key=lambda x: x[1]['points'], reverse=True)

    # Aggregate by country
    countries = defaultdict(lambda: {'points': 0, 'places': []})
    for place, data in sorted_places:
        country = data['country']
        countries[country]['points'] += data['points']
        countries[country]['places'].append(place.split(',')[0])

    sorted_countries = sorted(countries.items(), key=lambda x: x[1]['points'], reverse=True)

    # Aggregate by year
    years = defaultdict(lambda: {'points': 0, 'places': set()})
    for place, data in sorted_places:
        for year in data['years']:
            years[year]['points'] += data['points'] // len(data['years'])  # Approximate
            years[year]['places'].add(place.split(',')[0])

    # Overnight stays (night_points > 10 suggests overnight)
    overnight_places = [(p, d) for p, d in sorted_places if d['night_points'] > 10]
    overnight_places.sort(key=lambda x: x[1]['night_points'], reverse=True)

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
            <div class="stat-number">{max(years.keys()) - min(years.keys()) + 1}</div>
            <div class="stat-label">Years of Data</div>
        </div>
    </div>

    <div class="section">
    <h2>All Locations Ranked by Time Spent</h2>
    <table>
        <tr><th>#</th><th>Location</th><th>Points</th><th>First Visit</th><th>Last Visit</th></tr>
'''

    for i, (place, data) in enumerate(sorted_places, 1):
        first = str(data['first_seen'])[:10] if data['first_seen'] else '-'
        last = str(data['last_seen'])[:10] if data['last_seen'] else '-'
        html += f'        <tr><td>{i}</td><td>{place}</td><td>{data["points"]:,}</td><td>{first}</td><td>{last}</td></tr>\n'

    html += '''    </table>
    </div>

    <div class="section">
    <h2>Countries by Time Spent</h2>
    <table>
        <tr><th>#</th><th>Country</th><th>Points</th><th>Places Visited</th></tr>
'''

    for i, (country, data) in enumerate(sorted_countries, 1):
        places_str = ', '.join(data['places'][:8])
        if len(data['places']) > 8:
            places_str += f' (+{len(data["places"]) - 8} more)'
        html += f'        <tr><td>{i}</td><td>{country}</td><td>{data["points"]:,}</td><td>{places_str}</td></tr>\n'

    html += '''    </table>
    </div>

    <div class="section">
    <h2>Overnight Stays</h2>
    <p><em>Locations with significant nighttime points (23:00-06:00)</em></p>
    <table>
        <tr><th>#</th><th>Location</th><th>Night Points</th><th>Total Points</th><th>First Stay</th></tr>
'''

    for i, (place, data) in enumerate(overnight_places[:50], 1):
        first = str(data['first_seen'])[:10] if data['first_seen'] else '-'
        html += f'        <tr><td>{i}</td><td>{place}</td><td>{data["night_points"]:,}</td><td>{data["points"]:,}</td><td>{first}</td></tr>\n'

    html += '''    </table>
    </div>

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
    print("Fetching location clusters...")
    clusters = get_clusters(limit=200)
    print(f"Found {len(clusters)} clusters")

    print("Reverse geocoding (this takes a while due to rate limits)...")
    places = geocode_clusters(clusters)
    print(f"Identified {len(places)} distinct locations")

    print("Generating HTML report...")
    html = generate_html_report(places)

    # Save HTML to reports directory
    from pathlib import Path
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
