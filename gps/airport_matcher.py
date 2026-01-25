#!/usr/bin/env python3
"""Match flight coordinates to nearby airports.

Reads GPS-detected flights from /tmp/all_flights.txt and matches them to airports.
Optionally writes matched flights to the database with source='gps-detected'.
"""

import csv
import math
import requests
from io import StringIO
from collections import defaultdict
from datetime import datetime

import db

AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"

# Major train stations (Eurostar, high-speed rail, etc.)
TRAIN_STATIONS = [
    {'iata': 'STP', 'name': 'St Pancras International', 'city': 'London', 'country': 'UK', 'lat': 51.5308, 'lon': -0.1260},
    {'iata': 'XPG', 'name': 'Gare du Nord', 'city': 'Paris', 'country': 'France', 'lat': 48.8809, 'lon': 2.3553},
    {'iata': 'ZYR', 'name': 'Gare de Lyon', 'city': 'Paris', 'country': 'France', 'lat': 48.8448, 'lon': 2.3735},
    {'iata': 'XED', 'name': 'Gare de lEst', 'city': 'Paris', 'country': 'France', 'lat': 48.8763, 'lon': 2.3592},
    {'iata': 'ZYQ', 'name': 'Brussels Midi', 'city': 'Brussels', 'country': 'Belgium', 'lat': 50.8356, 'lon': 4.3369},
    {'iata': 'ZDH', 'name': 'Basel SBB', 'city': 'Basel', 'country': 'Switzerland', 'lat': 47.5472, 'lon': 7.5897},
    {'iata': 'ZLP', 'name': 'Zurich HB', 'city': 'Zurich', 'country': 'Switzerland', 'lat': 47.3783, 'lon': 8.5403},
    {'iata': 'XZN', 'name': 'Avignon TGV', 'city': 'Avignon', 'country': 'France', 'lat': 43.9217, 'lon': 4.7863},
    {'iata': 'XYG', 'name': 'Lyon Part-Dieu', 'city': 'Lyon', 'country': 'France', 'lat': 45.7606, 'lon': 4.8594},
    {'iata': 'QQS', 'name': 'St Pancras Intl', 'city': 'London', 'country': 'UK', 'lat': 51.5317, 'lon': -0.1261},  # Alternate code
    {'iata': 'XJZ', 'name': 'Amsterdam Centraal', 'city': 'Amsterdam', 'country': 'Netherlands', 'lat': 52.3791, 'lon': 4.9003},
    {'iata': 'ZFJ', 'name': 'Rennes', 'city': 'Rennes', 'country': 'France', 'lat': 48.1052, 'lon': -1.6722},
    {'iata': 'XDB', 'name': 'Lille Europe', 'city': 'Lille', 'country': 'France', 'lat': 50.6392, 'lon': 3.0762},
    {'iata': 'XOP', 'name': 'Poitiers', 'city': 'Poitiers', 'country': 'France', 'lat': 46.5826, 'lon': 0.3333},
    {'iata': 'ZFQ', 'name': 'Bordeaux St-Jean', 'city': 'Bordeaux', 'country': 'France', 'lat': 44.8256, 'lon': -0.5558},
    {'iata': 'XIZ', 'name': 'Strasbourg', 'city': 'Strasbourg', 'country': 'France', 'lat': 48.5850, 'lon': 7.7350},
    {'iata': 'XWG', 'name': 'Koln Hbf', 'city': 'Cologne', 'country': 'Germany', 'lat': 50.9430, 'lon': 6.9589},
    {'iata': 'QDU', 'name': 'Dusseldorf Hbf', 'city': 'Dusseldorf', 'country': 'Germany', 'lat': 51.2200, 'lon': 6.7942},
    {'iata': 'ZMB', 'name': 'Hamburg Hbf', 'city': 'Hamburg', 'country': 'Germany', 'lat': 53.5530, 'lon': 10.0069},
    {'iata': 'QPP', 'name': 'Berlin Hbf', 'city': 'Berlin', 'country': 'Germany', 'lat': 52.5250, 'lon': 13.3694},
    {'iata': 'ZMU', 'name': 'Munich Hbf', 'city': 'Munich', 'country': 'Germany', 'lat': 48.1403, 'lon': 11.5603},
    {'iata': 'XEA', 'name': 'Ashford Intl', 'city': 'Ashford', 'country': 'UK', 'lat': 51.1436, 'lon': 0.8761},
    {'iata': 'XQE', 'name': 'Ebbsfleet Intl', 'city': 'Ebbsfleet', 'country': 'UK', 'lat': 51.4428, 'lon': 0.3208},
]

def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def load_airports():
    """Download and parse OpenFlights airport database."""
    print("Downloading airport database...")
    resp = requests.get(AIRPORTS_URL, timeout=30)
    resp.raise_for_status()

    airports = []
    reader = csv.reader(StringIO(resp.text))
    for row in reader:
        if len(row) >= 8:
            try:
                airport = {
                    'id': row[0],
                    'name': row[1],
                    'city': row[2],
                    'country': row[3],
                    'iata': row[4] if row[4] != '\\N' else None,
                    'icao': row[5] if row[5] != '\\N' else None,
                    'lat': float(row[6]),
                    'lon': float(row[7]),
                }
                # Only include airports with IATA codes (major airports)
                if airport['iata']:
                    airports.append(airport)
            except (ValueError, IndexError):
                continue

    print(f"Loaded {len(airports)} airports with IATA codes")

    # Add train stations
    airports.extend(TRAIN_STATIONS)
    print(f"Added {len(TRAIN_STATIONS)} train stations")

    return airports

def find_nearest_airport(lat, lon, airports, max_distance_km=10):
    """Find the nearest airport within max_distance_km."""
    nearest = None
    min_dist = float('inf')

    for airport in airports:
        dist = haversine_km(lat, lon, airport['lat'], airport['lon'])
        if dist < min_dist and dist <= max_distance_km:
            min_dist = dist
            nearest = airport

    return nearest, min_dist if nearest else None

def load_flights(filepath='/tmp/all_flights.txt'):
    """Load flight data."""
    flights = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 9:
                flights.append({
                    'start_time': parts[0],
                    'start_lat': float(parts[1]),
                    'start_lon': float(parts[2]),
                    'end_time': parts[3],
                    'end_lat': float(parts[4]),
                    'end_lon': float(parts[5]),
                    'distance_km': int(float(parts[6])),
                    'duration_h': float(parts[7]),
                    'speed_kmh': int(float(parts[8])),
                })
    return flights

def format_airport(airport, dist):
    """Format airport info for display."""
    if airport:
        return f"{airport['iata']} ({airport['city']})"
    return None


def save_flights_to_database(matched_flights, dry_run=False):
    """
    Save GPS-detected flights to the flights database table.

    Args:
        matched_flights: List of flight dicts with matched airport info
        dry_run: If True, print what would be saved but don't insert
    """
    # Filter to only flights with both airports matched
    valid_flights = [f for f in matched_flights if f.get('start_airport') and f.get('end_airport')]

    if not valid_flights:
        print("No flights with matched airports to save")
        return

    print(f"\nSaving {len(valid_flights)} GPS-detected flights to database...")

    if dry_run:
        print("(Dry run - not actually inserting)")
        for f in valid_flights[:5]:
            print(f"  {f['start_time'][:10]} {f['start_airport']['iata']}->{f['end_airport']['iata']} {f['distance_km']}km")
        if len(valid_flights) > 5:
            print(f"  ... and {len(valid_flights) - 5} more")
        return

    conn = db.get_connection()
    cur = conn.cursor()

    sql = """
        INSERT INTO flights (
            date, dep_airport, dep_airport_name, dep_icao,
            arr_airport, arr_airport_name, arr_icao,
            dep_time, arr_time, duration,
            source, gps_matched,
            dep_lat, dep_lon, arr_lat, arr_lon, distance_km
        ) VALUES (
            %(date)s, %(dep_airport)s, %(dep_airport_name)s, %(dep_icao)s,
            %(arr_airport)s, %(arr_airport_name)s, %(arr_icao)s,
            %(dep_time)s, %(arr_time)s, %(duration)s,
            'gps-detected', TRUE,
            %(dep_lat)s, %(dep_lon)s, %(arr_lat)s, %(arr_lon)s, %(distance_km)s
        )
        ON CONFLICT (date, dep_airport, arr_airport, flight_number) DO NOTHING
    """

    inserted = 0
    skipped = 0

    for flight in valid_flights:
        start_airport = flight['start_airport']
        end_airport = flight['end_airport']

        # Parse times
        try:
            start_dt = datetime.fromisoformat(flight['start_time'].replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(flight['end_time'].replace('Z', '+00:00'))
            flight_date = start_dt.date()
            dep_time = start_dt.time()
            arr_time = end_dt.time()
            duration_hours = flight['duration_h']
            duration_str = f"{int(duration_hours)} hours {int((duration_hours % 1) * 60)} minutes"
        except (ValueError, KeyError):
            flight_date = flight['start_time'][:10]
            dep_time = None
            arr_time = None
            duration_str = None

        row = {
            'date': flight_date,
            'dep_airport': start_airport['iata'],
            'dep_airport_name': start_airport.get('name'),
            'dep_icao': start_airport.get('icao'),
            'arr_airport': end_airport['iata'],
            'arr_airport_name': end_airport.get('name'),
            'arr_icao': end_airport.get('icao'),
            'dep_time': dep_time,
            'arr_time': arr_time,
            'duration': duration_str,
            'dep_lat': flight['start_lat'],
            'dep_lon': flight['start_lon'],
            'arr_lat': flight['end_lat'],
            'arr_lon': flight['end_lon'],
            'distance_km': flight['distance_km'],
        }

        try:
            cur.execute(sql, row)
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"Error inserting {row['date']} {row['dep_airport']}->{row['arr_airport']}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    conn.close()

    print(f"Inserted {inserted} flights, skipped {skipped} duplicates")


def main(save_to_db=True, dry_run=False):
    airports = load_airports()
    flights = load_flights()

    print(f"\nMatching {len(flights)} flights to airports...")

    # Match each flight's start and end to airports
    matched_flights = []
    route_counts = defaultdict(lambda: {'count': 0, 'dates': []})

    for flight in flights:
        start_airport, start_dist = find_nearest_airport(
            flight['start_lat'], flight['start_lon'], airports
        )
        end_airport, end_dist = find_nearest_airport(
            flight['end_lat'], flight['end_lon'], airports
        )

        flight['start_airport'] = start_airport
        flight['start_dist'] = start_dist
        flight['end_airport'] = end_airport
        flight['end_dist'] = end_dist

        # Format for display
        if start_airport:
            flight['start_display'] = f"{start_airport['iata']}"
            flight['start_full'] = f"{start_airport['iata']} ({start_airport['name']})"
        else:
            flight['start_display'] = f"({flight['start_lat']:.1f}, {flight['start_lon']:.1f})"
            flight['start_full'] = flight['start_display']

        if end_airport:
            flight['end_display'] = f"{end_airport['iata']}"
            flight['end_full'] = f"{end_airport['iata']} ({end_airport['name']})"
        else:
            flight['end_display'] = f"({flight['end_lat']:.1f}, {flight['end_lon']:.1f})"
            flight['end_full'] = flight['end_display']

        matched_flights.append(flight)

        # Count routes
        route_key = f"{flight['start_display']} -> {flight['end_display']}"
        route_counts[route_key]['count'] += 1
        date = flight['start_time'][:10]
        route_counts[route_key]['dates'].append(date)
        if not route_counts[route_key].get('distance'):
            route_counts[route_key]['distance'] = flight['distance_km']

    # Sort routes by frequency
    sorted_routes = sorted(route_counts.items(), key=lambda x: -x[1]['count'])

    # Generate report
    output = []
    output.append("# All Flights Report (Airport-Matched)")
    output.append("")
    output.append(f"Journeys >200km with start/end points matched to airports within 10km.")
    output.append("")
    output.append(f"**Total journeys:** {len(matched_flights)}")
    output.append(f"**Unique routes:** {len(sorted_routes)}")

    # Count airport matches
    start_matched = sum(1 for f in matched_flights if f['start_airport'])
    end_matched = sum(1 for f in matched_flights if f['end_airport'])
    output.append(f"**Departures matched to airports:** {start_matched} ({100*start_matched/len(matched_flights):.0f}%)")
    output.append(f"**Arrivals matched to airports:** {end_matched} ({100*end_matched/len(matched_flights):.0f}%)")
    output.append("")

    # Routes by frequency
    output.append("## Routes by Frequency")
    output.append("")
    output.append("| # | Count | Route | Distance | Sample Dates |")
    output.append("|---|-------|-------|----------|--------------|")

    for i, (route, data) in enumerate(sorted_routes[:50], 1):
        dates = data['dates'][:3]
        more = f" (+{len(data['dates'])-3})" if len(data['dates']) > 3 else ""
        output.append(f"| {i} | {data['count']} | {route} | {data['distance']}km | {', '.join(dates)}{more} |")

    output.append("")

    # All journeys chronologically
    output.append("## All Journeys Chronologically")
    output.append("")
    output.append("| Date | From | To | Distance | Duration |")
    output.append("|------|------|-----|----------|----------|")

    for flight in matched_flights:
        date = flight['start_time'][:10]
        output.append(f"| {date} | {flight['start_full']} | {flight['end_full']} | {flight['distance_km']}km | {flight['duration_h']:.1f}h |")

    # Write output
    report = '\n'.join(output)

    with open('/home/stu/all_flights.md', 'w') as f:
        f.write(report)
    print(f"\nReport written to /home/stu/all_flights.md")

    # Also save raw matched data for reference
    with open('/tmp/all_flights_airports.txt', 'w') as f:
        for flight in matched_flights:
            start_code = flight['start_airport']['iata'] if flight['start_airport'] else ''
            end_code = flight['end_airport']['iata'] if flight['end_airport'] else ''
            f.write(f"{flight['start_time']}|{start_code}|{flight['start_lat']}|{flight['start_lon']}|")
            f.write(f"{flight['end_time']}|{end_code}|{flight['end_lat']}|{flight['end_lon']}|")
            f.write(f"{flight['distance_km']}|{flight['duration_h']}\n")

    print(f"Raw data written to /tmp/all_flights_airports.txt")

    # Save to database
    if save_to_db:
        save_flights_to_database(matched_flights, dry_run=dry_run)

    return matched_flights


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Match GPS flights to airports')
    parser.add_argument('--no-db', action='store_true', help='Skip database insert')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no inserts)')
    args = parser.parse_args()

    main(save_to_db=not args.no_db, dry_run=args.dry_run)
