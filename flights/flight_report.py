#!/usr/bin/env python3
"""
Generate flight analysis reports from the flights database.

Outputs:
- ~/flight_report.html - Interactive HTML report
- ~/flight_report.md - Markdown summary
"""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import db

REPORTS_DIR = Path(__file__).parent.parent / "reports"
OUTPUT_HTML = REPORTS_DIR / "flight_report.html"
OUTPUT_MD = REPORTS_DIR / "flight_report.md"


def get_all_flights(cur):
    """Get all flights from database."""
    cur.execute("""
        SELECT date, flight_number, dep_airport, dep_airport_name, arr_airport, arr_airport_name,
               dep_time, arr_time, duration, airline, airline_code, aircraft_type, aircraft_code,
               registration, seat_number, seat_type, flight_class, flight_reason, notes, source,
               dep_lat, dep_lon, arr_lat, arr_lon, distance_km
        FROM flights
        ORDER BY date DESC, dep_time DESC
    """)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def calculate_statistics(flights):
    """Calculate comprehensive flight statistics."""
    stats = {
        'total_flights': len(flights),
        'total_distance_km': sum(f['distance_km'] or 0 for f in flights),
        'flights_with_duration': [],
        'flights_by_year': defaultdict(int),
        'flights_by_airline': defaultdict(int),
        'flights_by_aircraft': defaultdict(int),
        'flights_by_aircraft_code': defaultdict(int),
        'routes': defaultdict(lambda: {'count': 0, 'distance_km': 0}),
        'airports_dep': defaultdict(int),
        'airports_arr': defaultdict(int),
        'seat_types': defaultdict(int),
        'flight_classes': defaultdict(int),
        'flight_reasons': defaultdict(int),
        'sources': defaultdict(int),
        'registrations': set(),
        'airlines': set(),
        'aircraft_types': set(),
    }

    # Calculate total flight time from duration intervals
    total_minutes = 0

    for f in flights:
        # Year stats
        if f['date']:
            year = f['date'].year
            stats['flights_by_year'][year] += 1

        # Airline stats
        airline = f['airline'] or f['airline_code'] or 'Unknown'
        stats['flights_by_airline'][airline] += 1
        if f['airline']:
            stats['airlines'].add(f['airline'])

        # Aircraft stats
        aircraft = f['aircraft_type'] or f['aircraft_code'] or 'Unknown'
        stats['flights_by_aircraft'][aircraft] += 1
        if f['aircraft_code']:
            stats['flights_by_aircraft_code'][f['aircraft_code']] += 1
        if f['aircraft_type']:
            stats['aircraft_types'].add(f['aircraft_type'])

        # Route stats
        route = f"{f['dep_airport']}-{f['arr_airport']}"
        stats['routes'][route]['count'] += 1
        stats['routes'][route]['distance_km'] = f['distance_km'] or 0
        stats['routes'][route]['dep_name'] = f['dep_airport_name']
        stats['routes'][route]['arr_name'] = f['arr_airport_name']

        # Airport stats
        stats['airports_dep'][f['dep_airport']] += 1
        stats['airports_arr'][f['arr_airport']] += 1

        # Seat type (1=window, 2=middle, 3=aisle)
        if f['seat_type']:
            seat_map = {1: 'Window', 2: 'Middle', 3: 'Aisle'}
            stats['seat_types'][seat_map.get(f['seat_type'], 'Unknown')] += 1

        # Flight class (1=economy, 2=business, etc.)
        if f['flight_class']:
            class_map = {1: 'Economy', 2: 'Business', 3: 'First', 4: 'Economy Plus'}
            stats['flight_classes'][class_map.get(f['flight_class'], 'Other')] += 1

        # Flight reason (1=leisure, 2=business)
        if f['flight_reason']:
            reason_map = {1: 'Leisure', 2: 'Business'}
            stats['flight_reasons'][reason_map.get(f['flight_reason'], 'Other')] += 1

        # Source stats
        stats['sources'][f['source'] or 'unknown'] += 1

        # Unique registrations
        if f['registration']:
            stats['registrations'].add(f['registration'])

        # Duration calculation (handle PostgreSQL interval)
        if f['duration']:
            duration = f['duration']
            if hasattr(duration, 'total_seconds'):
                total_minutes += duration.total_seconds() / 60
            elif isinstance(duration, str):
                # Parse "HH:MM:SS" or interval string
                parts = duration.split(':')
                if len(parts) >= 2:
                    try:
                        total_minutes += int(parts[0]) * 60 + int(parts[1])
                    except ValueError:
                        pass

    stats['total_flight_hours'] = total_minutes / 60
    stats['unique_airports'] = set(stats['airports_dep'].keys()) | set(stats['airports_arr'].keys())
    stats['unique_airlines'] = len(stats['airlines'])
    stats['unique_aircraft'] = len(stats['aircraft_types'])
    stats['unique_registrations'] = len(stats['registrations'])

    return stats


def format_distance(km):
    """Format distance with commas."""
    return f"{km:,}"


def generate_markdown(flights, stats):
    """Generate markdown report."""
    lines = []
    lines.append("# Flight Report")
    lines.append("")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    # Overall statistics
    lines.append("## Overall Statistics")
    lines.append("")
    lines.append(f"- **Total Flights:** {stats['total_flights']}")
    lines.append(f"- **Total Distance:** {format_distance(stats['total_distance_km'])} km ({format_distance(int(stats['total_distance_km'] * 0.621371))} miles)")
    lines.append(f"- **Total Flight Time:** {stats['total_flight_hours']:.0f} hours ({stats['total_flight_hours']/24:.1f} days)")
    lines.append(f"- **Unique Airports:** {len(stats['unique_airports'])}")
    lines.append(f"- **Unique Airlines:** {stats['unique_airlines']}")
    lines.append(f"- **Unique Aircraft Types:** {stats['unique_aircraft']}")
    lines.append(f"- **Unique Aircraft (by registration):** {stats['unique_registrations']}")
    lines.append("")

    # Flights by Year
    lines.append("## Flights by Year")
    lines.append("")
    lines.append("| Year | Flights |")
    lines.append("|------|---------|")
    for year in sorted(stats['flights_by_year'].keys(), reverse=True):
        lines.append(f"| {year} | {stats['flights_by_year'][year]} |")
    lines.append("")

    # Top Airlines
    lines.append("## Top Airlines")
    lines.append("")
    lines.append("| Airline | Flights |")
    lines.append("|---------|---------|")
    sorted_airlines = sorted(stats['flights_by_airline'].items(), key=lambda x: -x[1])
    for airline, count in sorted_airlines[:15]:
        lines.append(f"| {airline} | {count} |")
    lines.append("")

    # Top Aircraft Types
    lines.append("## Top Aircraft Types")
    lines.append("")
    lines.append("| Aircraft | Flights |")
    lines.append("|----------|---------|")
    sorted_aircraft = sorted(stats['flights_by_aircraft'].items(), key=lambda x: -x[1])
    for aircraft, count in sorted_aircraft[:15]:
        lines.append(f"| {aircraft} | {count} |")
    lines.append("")

    # Most Frequent Routes
    lines.append("## Most Frequent Routes")
    lines.append("")
    lines.append("| Route | Flights | Distance |")
    lines.append("|-------|---------|----------|")
    sorted_routes = sorted(stats['routes'].items(), key=lambda x: -x[1]['count'])
    for route, data in sorted_routes[:20]:
        lines.append(f"| {route} | {data['count']} | {data['distance_km']} km |")
    lines.append("")

    # Airports
    lines.append("## Airports Visited")
    lines.append("")
    all_airports = defaultdict(int)
    for apt, count in stats['airports_dep'].items():
        all_airports[apt] += count
    for apt, count in stats['airports_arr'].items():
        all_airports[apt] += count

    lines.append("| Airport | Departures | Arrivals | Total |")
    lines.append("|---------|------------|----------|-------|")
    sorted_airports = sorted(all_airports.items(), key=lambda x: -x[1])
    for apt, total in sorted_airports[:25]:
        dep = stats['airports_dep'].get(apt, 0)
        arr = stats['airports_arr'].get(apt, 0)
        lines.append(f"| {apt} | {dep} | {arr} | {total} |")
    lines.append("")

    # Seat Preferences
    if stats['seat_types']:
        lines.append("## Seat Preferences")
        lines.append("")
        total_seats = sum(stats['seat_types'].values())
        for seat_type, count in sorted(stats['seat_types'].items(), key=lambda x: -x[1]):
            pct = 100 * count / total_seats
            lines.append(f"- **{seat_type}:** {count} ({pct:.1f}%)")
        lines.append("")

    # Flight Class
    if stats['flight_classes']:
        lines.append("## Flight Classes")
        lines.append("")
        for fclass, count in sorted(stats['flight_classes'].items(), key=lambda x: -x[1]):
            lines.append(f"- **{fclass}:** {count}")
        lines.append("")

    # Flight Reason
    if stats['flight_reasons']:
        lines.append("## Flight Reasons")
        lines.append("")
        for reason, count in sorted(stats['flight_reasons'].items(), key=lambda x: -x[1]):
            lines.append(f"- **{reason}:** {count}")
        lines.append("")

    # Data Sources
    lines.append("## Data Sources")
    lines.append("")
    for source, count in sorted(stats['sources'].items()):
        lines.append(f"- **{source}:** {count} flights")
    lines.append("")

    return "\n".join(lines)


def generate_html(flights, stats):
    """Generate interactive HTML report."""
    html = []
    html.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Flight Report</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }
        h1 { color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px; }
        h2 { color: #444; margin-top: 30px; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-card .number {
            font-size: 2em;
            font-weight: bold;
            color: #1a73e8;
        }
        .stat-card .label {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin: 15px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }
        tr:hover { background: #f8f9fa; }
        .section { margin-bottom: 40px; }
        .generated {
            color: #888;
            font-size: 0.9em;
            margin-bottom: 20px;
        }
        .two-col {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
        }
    </style>
</head>
<body>
""")

    html.append(f"<h1>Flight Report</h1>")
    html.append(f"<p class='generated'>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>")

    # Stats cards
    html.append("<div class='stats-grid'>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_flights']}</div><div class='label'>Total Flights</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{format_distance(stats['total_distance_km'])}</div><div class='label'>Total KM</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_flight_hours']:.0f}</div><div class='label'>Flight Hours</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{len(stats['unique_airports'])}</div><div class='label'>Airports</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['unique_airlines']}</div><div class='label'>Airlines</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['unique_aircraft']}</div><div class='label'>Aircraft Types</div></div>")
    html.append("</div>")

    # Two column layout for smaller tables
    html.append("<div class='two-col'>")

    # Flights by Year
    html.append("<div class='section'>")
    html.append("<h2>Flights by Year</h2>")
    html.append("<table><tr><th>Year</th><th>Flights</th></tr>")
    for year in sorted(stats['flights_by_year'].keys(), reverse=True):
        html.append(f"<tr><td>{year}</td><td>{stats['flights_by_year'][year]}</td></tr>")
    html.append("</table></div>")

    # Top Airlines
    html.append("<div class='section'>")
    html.append("<h2>Top Airlines</h2>")
    html.append("<table><tr><th>Airline</th><th>Flights</th></tr>")
    sorted_airlines = sorted(stats['flights_by_airline'].items(), key=lambda x: -x[1])
    for airline, count in sorted_airlines[:12]:
        html.append(f"<tr><td>{airline}</td><td>{count}</td></tr>")
    html.append("</table></div>")

    html.append("</div>")  # end two-col

    # Top Aircraft
    html.append("<div class='section'>")
    html.append("<h2>Top Aircraft Types</h2>")
    html.append("<table><tr><th>Aircraft</th><th>Flights</th></tr>")
    sorted_aircraft = sorted(stats['flights_by_aircraft'].items(), key=lambda x: -x[1])
    for aircraft, count in sorted_aircraft[:15]:
        html.append(f"<tr><td>{aircraft}</td><td>{count}</td></tr>")
    html.append("</table></div>")

    # Most Frequent Routes
    html.append("<div class='section'>")
    html.append("<h2>Most Frequent Routes</h2>")
    html.append("<table><tr><th>Route</th><th>Flights</th><th>Distance</th></tr>")
    sorted_routes = sorted(stats['routes'].items(), key=lambda x: -x[1]['count'])
    for route, data in sorted_routes[:20]:
        html.append(f"<tr><td>{route}</td><td>{data['count']}</td><td>{data['distance_km']} km</td></tr>")
    html.append("</table></div>")

    # Airports
    html.append("<div class='section'>")
    html.append("<h2>Airports Visited</h2>")
    html.append("<table><tr><th>Airport</th><th>Departures</th><th>Arrivals</th><th>Total</th></tr>")
    all_airports = defaultdict(int)
    for apt, count in stats['airports_dep'].items():
        all_airports[apt] += count
    for apt, count in stats['airports_arr'].items():
        all_airports[apt] += count
    sorted_airports = sorted(all_airports.items(), key=lambda x: -x[1])
    for apt, total in sorted_airports[:25]:
        dep = stats['airports_dep'].get(apt, 0)
        arr = stats['airports_arr'].get(apt, 0)
        html.append(f"<tr><td>{apt}</td><td>{dep}</td><td>{arr}</td><td>{total}</td></tr>")
    html.append("</table></div>")

    # Recent Flights
    html.append("<div class='section'>")
    html.append("<h2>Recent Flights</h2>")
    html.append("<table><tr><th>Date</th><th>Flight</th><th>Route</th><th>Airline</th><th>Aircraft</th></tr>")
    for f in flights[:30]:
        date = f['date'].strftime('%Y-%m-%d') if f['date'] else ''
        flight_num = f['flight_number'] or ''
        route = f"{f['dep_airport']}-{f['arr_airport']}"
        airline = f['airline_code'] or ''
        aircraft = f['aircraft_code'] or ''
        html.append(f"<tr><td>{date}</td><td>{flight_num}</td><td>{route}</td><td>{airline}</td><td>{aircraft}</td></tr>")
    html.append("</table></div>")

    html.append("</body></html>")

    return "\n".join(html)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate flight reports')
    parser.add_argument('--html', action='store_true', help='Generate HTML only')
    parser.add_argument('--md', action='store_true', help='Generate Markdown only')
    args = parser.parse_args()

    # Default to both if neither specified
    if not args.html and not args.md:
        args.html = True
        args.md = True

    print("Fetching flight data...")
    conn = db.get_connection()
    cur = conn.cursor()

    flights = get_all_flights(cur)
    print(f"Found {len(flights)} flights")

    cur.close()
    conn.close()

    if not flights:
        print("No flights found in database")
        return

    print("Calculating statistics...")
    stats = calculate_statistics(flights)

    if args.md:
        print(f"Generating markdown report...")
        md_report = generate_markdown(flights, stats)
        with open(OUTPUT_MD, 'w') as f:
            f.write(md_report)
        print(f"Wrote {OUTPUT_MD}")

    if args.html:
        print(f"Generating HTML report...")
        html_report = generate_html(flights, stats)
        with open(OUTPUT_HTML, 'w') as f:
            f.write(html_report)
        print(f"Wrote {OUTPUT_HTML}")

    print("Done!")


if __name__ == '__main__':
    main()
