#!/usr/bin/env python3
"""
Generate GA flying logbook analysis reports.

Outputs:
- reports/ga_report.html - Interactive HTML report
- reports/ga_report.md - Markdown summary
"""

import sys
import csv
import requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from io import StringIO

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import db

AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
_airports_cache = None


def load_airports():
    """Download and parse OpenFlights airport database."""
    global _airports_cache
    if _airports_cache is not None:
        return _airports_cache

    print("Downloading airport database...")
    resp = requests.get(AIRPORTS_URL, timeout=30)
    resp.raise_for_status()

    airports = {}
    reader = csv.reader(StringIO(resp.text))
    for row in reader:
        if len(row) >= 8:
            try:
                icao = row[5] if row[5] != '\\N' else None
                if icao:
                    airports[icao] = {
                        'name': row[1],
                        'city': row[2],
                        'country': row[3],
                    }
            except (ValueError, IndexError):
                continue

    print(f"Loaded {len(airports)} airports")
    _airports_cache = airports
    return airports


def format_airport(icao, airports):
    """Format airport code with name in brackets."""
    if not icao:
        return icao
    info = airports.get(icao)
    if info:
        name = info['name'].replace(' Airport', '').replace(' Aerodrome', '')
        return f"{icao} ({name})"
    return icao

REPORTS_DIR = Path(__file__).parent.parent / "reports"
OUTPUT_HTML = REPORTS_DIR / "ga_report.html"
OUTPUT_MD = REPORTS_DIR / "ga_report.md"


def get_all_flights(cur):
    """Get all GA flights from database."""
    cur.execute("""
        SELECT date, aircraft_type, registration, captain, operating_capacity,
               dep_airport, arr_airport, dep_time, arr_time,
               hours_sep_pic, hours_sep_dual, hours_mep_pic, hours_mep_dual,
               hours_pic_3, hours_dual_3, hours_pic_4, hours_dual_4,
               hours_instrument, hours_as_instructor, hours_total, instructor, exercise
        FROM ga_flights
        ORDER BY date DESC, dep_time DESC
    """)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def calculate_statistics(flights):
    """Calculate comprehensive GA flight statistics."""
    stats = {
        'total_flights': len(flights),
        'total_hours': 0,
        'hours_sep_pic': 0,
        'hours_sep_dual': 0,
        'hours_mep_pic': 0,
        'hours_mep_dual': 0,
        'hours_instrument': 0,
        'hours_as_instructor': 0,
        'flights_by_year': defaultdict(lambda: {'count': 0, 'hours': 0}),
        'flights_by_type': defaultdict(lambda: {'count': 0, 'hours': 0}),
        'flights_by_registration': defaultdict(lambda: {'count': 0, 'hours': 0, 'type': None}),
        'flights_by_instructor': defaultdict(lambda: {'count': 0, 'hours': 0}),
        'flights_by_capacity': defaultdict(int),
        'airports': defaultdict(int),
        'routes': defaultdict(int),
        'date_range': {'first': None, 'last': None},
        'records': {
            'longest_flight': None,
            'most_flights_day': None,
        }
    }

    flights_by_date = defaultdict(list)

    for f in flights:
        # Total hours
        hours = float(f['hours_total'] or 0)
        stats['total_hours'] += hours

        # Hour categories
        stats['hours_sep_pic'] += float(f['hours_sep_pic'] or 0)
        stats['hours_sep_dual'] += float(f['hours_sep_dual'] or 0)
        stats['hours_mep_pic'] += float(f['hours_mep_pic'] or 0)
        stats['hours_mep_dual'] += float(f['hours_mep_dual'] or 0)
        stats['hours_instrument'] += float(f['hours_instrument'] or 0)
        stats['hours_as_instructor'] += float(f['hours_as_instructor'] or 0)

        # By year
        if f['date']:
            year = f['date'].year
            stats['flights_by_year'][year]['count'] += 1
            stats['flights_by_year'][year]['hours'] += hours

            # Track date range
            if stats['date_range']['first'] is None or f['date'] < stats['date_range']['first']:
                stats['date_range']['first'] = f['date']
            if stats['date_range']['last'] is None or f['date'] > stats['date_range']['last']:
                stats['date_range']['last'] = f['date']

            # Track flights by date for records
            flights_by_date[f['date']].append(f)

        # By aircraft type
        atype = f['aircraft_type'] or 'Unknown'
        stats['flights_by_type'][atype]['count'] += 1
        stats['flights_by_type'][atype]['hours'] += hours

        # By registration
        reg = f['registration'] or 'Unknown'
        stats['flights_by_registration'][reg]['count'] += 1
        stats['flights_by_registration'][reg]['hours'] += hours
        stats['flights_by_registration'][reg]['type'] = atype

        # By instructor (captain on training flights, exclude "Self" for solo)
        instructor = f['instructor'] or f['captain']
        if instructor and instructor.lower() != 'self':
            dual_hours = float(f['hours_sep_dual'] or 0) + float(f['hours_mep_dual'] or 0)
            if dual_hours > 0:  # Only count as instructor if there were dual hours
                stats['flights_by_instructor'][instructor]['count'] += 1
                stats['flights_by_instructor'][instructor]['hours'] += dual_hours

        # By operating capacity
        capacity = f['operating_capacity'] or 'Unknown'
        stats['flights_by_capacity'][capacity] += 1

        # Airports
        if f['dep_airport']:
            stats['airports'][f['dep_airport']] += 1
        if f['arr_airport']:
            stats['airports'][f['arr_airport']] += 1

        # Routes
        if f['dep_airport'] and f['arr_airport']:
            route = f"{f['dep_airport']}-{f['arr_airport']}"
            stats['routes'][route] += 1

        # Track longest flight
        if hours > 0:
            if (stats['records']['longest_flight'] is None or
                hours > stats['records']['longest_flight']['hours']):
                stats['records']['longest_flight'] = {
                    'date': f['date'],
                    'hours': hours,
                    'registration': f['registration'],
                    'route': f"{f['dep_airport']}-{f['arr_airport']}"
                }

    # Find day with most flights
    if flights_by_date:
        max_date = max(flights_by_date.keys(), key=lambda d: len(flights_by_date[d]))
        stats['records']['most_flights_day'] = {
            'date': max_date,
            'count': len(flights_by_date[max_date])
        }

    # Calculate derived stats
    stats['hours_pic'] = stats['hours_sep_pic'] + stats['hours_mep_pic']
    stats['hours_dual'] = stats['hours_sep_dual'] + stats['hours_mep_dual']
    stats['unique_aircraft'] = len(stats['flights_by_registration'])
    stats['unique_airports'] = len(stats['airports'])
    stats['unique_types'] = len(stats['flights_by_type'])

    return stats


def format_hours(h):
    """Format hours as HH:MM."""
    hours = int(h)
    minutes = int((h - hours) * 60)
    return f"{hours}:{minutes:02d}"


def generate_markdown(flights, stats, airports):
    """Generate markdown report."""
    lines = []
    lines.append("# GA Flying Logbook Report")
    lines.append("")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    if stats['date_range']['first'] and stats['date_range']['last']:
        lines.append(f"**Date Range:** {stats['date_range']['first']} to {stats['date_range']['last']}")
        lines.append("")

    # Overall statistics
    lines.append("## Overall Statistics")
    lines.append("")
    lines.append(f"- **Total Flights:** {stats['total_flights']}")
    lines.append(f"- **Total Flight Time:** {format_hours(stats['total_hours'])} ({stats['total_hours']:.1f} hours)")
    lines.append(f"- **Unique Aircraft:** {stats['unique_aircraft']}")
    lines.append(f"- **Unique Airports:** {stats['unique_airports']}")
    lines.append(f"- **Aircraft Types Flown:** {stats['unique_types']}")
    lines.append("")

    # Hour breakdown
    lines.append("## Hours Breakdown")
    lines.append("")
    lines.append("### By Category")
    lines.append(f"- **Pilot in Command (PIC):** {format_hours(stats['hours_pic'])} ({stats['hours_pic']:.1f}h)")
    lines.append(f"  - Single Engine: {format_hours(stats['hours_sep_pic'])}")
    lines.append(f"  - Multi Engine: {format_hours(stats['hours_mep_pic'])}")
    lines.append(f"- **Dual (Training):** {format_hours(stats['hours_dual'])} ({stats['hours_dual']:.1f}h)")
    lines.append(f"  - Single Engine: {format_hours(stats['hours_sep_dual'])}")
    lines.append(f"  - Multi Engine: {format_hours(stats['hours_mep_dual'])}")
    lines.append(f"- **Instrument Flying:** {format_hours(stats['hours_instrument'])}")
    lines.append(f"- **As Instructor:** {format_hours(stats['hours_as_instructor'])}")
    lines.append("")

    # Flights by Year
    lines.append("## Flights by Year")
    lines.append("")
    lines.append("| Year | Flights | Hours |")
    lines.append("|------|---------|-------|")
    for year in sorted(stats['flights_by_year'].keys(), reverse=True):
        data = stats['flights_by_year'][year]
        lines.append(f"| {year} | {data['count']} | {format_hours(data['hours'])} |")
    lines.append("")

    # By Aircraft Type
    lines.append("## By Aircraft Type")
    lines.append("")
    lines.append("| Type | Flights | Hours |")
    lines.append("|------|---------|-------|")
    sorted_types = sorted(stats['flights_by_type'].items(), key=lambda x: -x[1]['hours'])
    for atype, data in sorted_types:
        lines.append(f"| {atype} | {data['count']} | {format_hours(data['hours'])} |")
    lines.append("")

    # By Registration
    lines.append("## By Aircraft Registration")
    lines.append("")
    lines.append("| Registration | Type | Flights | Hours |")
    lines.append("|--------------|------|---------|-------|")
    sorted_regs = sorted(stats['flights_by_registration'].items(), key=lambda x: -x[1]['hours'])
    for reg, data in sorted_regs[:20]:
        lines.append(f"| {reg} | {data['type']} | {data['count']} | {format_hours(data['hours'])} |")
    lines.append("")

    # By Instructor
    if stats['flights_by_instructor']:
        lines.append("## Training by Instructor")
        lines.append("")
        total_instr_hours = sum(d['hours'] for d in stats['flights_by_instructor'].values())
        total_instr_flights = sum(d['count'] for d in stats['flights_by_instructor'].values())
        lines.append(f"**Total Training:** {total_instr_flights} flights, {format_hours(total_instr_hours)} hours with instructors")
        lines.append("")
        lines.append("| Instructor | Flights | Dual Hours |")
        lines.append("|------------|---------|------------|")
        sorted_instr = sorted(stats['flights_by_instructor'].items(), key=lambda x: -x[1]['hours'])
        for instr, data in sorted_instr:
            lines.append(f"| {instr} | {data['count']} | {format_hours(data['hours'])} |")
        lines.append("")

    # Operating Capacity
    lines.append("## By Operating Capacity")
    lines.append("")
    capacity_labels = {
        'PUT': 'Pilot Under Training',
        'P1': 'Pilot in Command',
        'P2': 'Co-Pilot',
        'P/UT': 'Pilot Under Training',
    }
    for capacity, count in sorted(stats['flights_by_capacity'].items(), key=lambda x: -x[1]):
        label = capacity_labels.get(capacity, capacity)
        lines.append(f"- **{capacity}** ({label}): {count} flights")
    lines.append("")

    # Most Visited Airports
    lines.append("## Airports")
    lines.append("")
    lines.append("| Airport | Visits |")
    lines.append("|---------|--------|")
    sorted_airports = sorted(stats['airports'].items(), key=lambda x: -x[1])
    for airport, count in sorted_airports[:15]:
        lines.append(f"| {format_airport(airport, airports)} | {count} |")
    lines.append("")

    # Most Frequent Routes
    lines.append("## Most Frequent Routes")
    lines.append("")
    lines.append("| Route | Flights |")
    lines.append("|-------|---------|")
    sorted_routes = sorted(stats['routes'].items(), key=lambda x: -x[1])
    for route, count in sorted_routes[:15]:
        # Format route with airport names
        parts = route.split('-')
        if len(parts) == 2:
            formatted = f"{format_airport(parts[0], airports)} - {format_airport(parts[1], airports)}"
        else:
            formatted = route
        lines.append(f"| {formatted} | {count} |")
    lines.append("")

    # Records
    lines.append("## Records")
    lines.append("")
    if stats['records']['longest_flight']:
        lf = stats['records']['longest_flight']
        route_parts = lf['route'].split('-')
        if len(route_parts) == 2:
            route_fmt = f"{format_airport(route_parts[0], airports)} - {format_airport(route_parts[1], airports)}"
        else:
            route_fmt = lf['route']
        lines.append(f"- **Longest Flight:** {format_hours(lf['hours'])} on {lf['date']} ({lf['registration']}, {route_fmt})")
    if stats['records']['most_flights_day']:
        mf = stats['records']['most_flights_day']
        lines.append(f"- **Most Flights in a Day:** {mf['count']} on {mf['date']}")
    lines.append("")

    return "\n".join(lines)


def generate_html(flights, stats, airports):
    """Generate interactive HTML report."""
    html = []
    html.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GA Flying Logbook Report</title>
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
        h1 { color: #2e7d32; border-bottom: 2px solid #2e7d32; padding-bottom: 10px; }
        h2 { color: #444; margin-top: 30px; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
            font-size: 1.8em;
            font-weight: bold;
            color: #2e7d32;
        }
        .stat-card .label {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }
        .hours-breakdown {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .hours-card {
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .hours-card h3 {
            margin: 0 0 10px 0;
            color: #555;
            font-size: 1em;
        }
        .hours-card .main {
            font-size: 1.5em;
            font-weight: bold;
            color: #2e7d32;
        }
        .hours-card .sub {
            color: #888;
            font-size: 0.85em;
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
        .record {
            background: #e8f5e9;
            padding: 10px 15px;
            border-radius: 6px;
            margin: 5px 0;
        }
    </style>
</head>
<body>
""")

    html.append("<h1>GA Flying Logbook Report</h1>")
    html.append(f"<p class='generated'>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>")

    if stats['date_range']['first'] and stats['date_range']['last']:
        html.append(f"<p><strong>Date Range:</strong> {stats['date_range']['first']} to {stats['date_range']['last']}</p>")

    # Stats cards
    html.append("<div class='stats-grid'>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_flights']}</div><div class='label'>Total Flights</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{format_hours(stats['total_hours'])}</div><div class='label'>Total Hours</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['unique_aircraft']}</div><div class='label'>Unique Aircraft</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['unique_airports']}</div><div class='label'>Airports</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['unique_types']}</div><div class='label'>Aircraft Types</div></div>")
    html.append("</div>")

    # Hours breakdown
    html.append("<h2>Hours Breakdown</h2>")
    html.append("<div class='hours-breakdown'>")
    html.append(f"""<div class='hours-card'>
        <h3>Pilot in Command</h3>
        <div class='main'>{format_hours(stats['hours_pic'])}</div>
        <div class='sub'>SEP: {format_hours(stats['hours_sep_pic'])} | MEP: {format_hours(stats['hours_mep_pic'])}</div>
    </div>""")
    html.append(f"""<div class='hours-card'>
        <h3>Dual (Training)</h3>
        <div class='main'>{format_hours(stats['hours_dual'])}</div>
        <div class='sub'>SEP: {format_hours(stats['hours_sep_dual'])} | MEP: {format_hours(stats['hours_mep_dual'])}</div>
    </div>""")
    html.append(f"""<div class='hours-card'>
        <h3>Instrument Flying</h3>
        <div class='main'>{format_hours(stats['hours_instrument'])}</div>
    </div>""")
    html.append(f"""<div class='hours-card'>
        <h3>As Instructor</h3>
        <div class='main'>{format_hours(stats['hours_as_instructor'])}</div>
    </div>""")
    html.append("</div>")

    # Records
    html.append("<h2>Records</h2>")
    if stats['records']['longest_flight']:
        lf = stats['records']['longest_flight']
        route_parts = lf['route'].split('-')
        if len(route_parts) == 2:
            route_fmt = f"{format_airport(route_parts[0], airports)} - {format_airport(route_parts[1], airports)}"
        else:
            route_fmt = lf['route']
        html.append(f"<div class='record'><strong>Longest Flight:</strong> {format_hours(lf['hours'])} on {lf['date']} ({lf['registration']}, {route_fmt})</div>")
    if stats['records']['most_flights_day']:
        mf = stats['records']['most_flights_day']
        html.append(f"<div class='record'><strong>Most Flights in a Day:</strong> {mf['count']} on {mf['date']}</div>")

    # Two column layout
    html.append("<div class='two-col'>")

    # Flights by Year
    html.append("<div class='section'>")
    html.append("<h2>Flights by Year</h2>")
    html.append("<table><tr><th>Year</th><th>Flights</th><th>Hours</th></tr>")
    for year in sorted(stats['flights_by_year'].keys(), reverse=True):
        data = stats['flights_by_year'][year]
        html.append(f"<tr><td>{year}</td><td>{data['count']}</td><td>{format_hours(data['hours'])}</td></tr>")
    html.append("</table></div>")

    # By Aircraft Type
    html.append("<div class='section'>")
    html.append("<h2>By Aircraft Type</h2>")
    html.append("<table><tr><th>Type</th><th>Flights</th><th>Hours</th></tr>")
    sorted_types = sorted(stats['flights_by_type'].items(), key=lambda x: -x[1]['hours'])
    for atype, data in sorted_types:
        html.append(f"<tr><td>{atype}</td><td>{data['count']}</td><td>{format_hours(data['hours'])}</td></tr>")
    html.append("</table></div>")

    html.append("</div>")  # end two-col

    # By Registration
    html.append("<div class='section'>")
    html.append("<h2>Aircraft Flown</h2>")
    html.append("<table><tr><th>Registration</th><th>Type</th><th>Flights</th><th>Hours</th></tr>")
    sorted_regs = sorted(stats['flights_by_registration'].items(), key=lambda x: -x[1]['hours'])
    for reg, data in sorted_regs[:20]:
        html.append(f"<tr><td>{reg}</td><td>{data['type']}</td><td>{data['count']}</td><td>{format_hours(data['hours'])}</td></tr>")
    html.append("</table></div>")

    # By Instructor
    if stats['flights_by_instructor']:
        total_instr_hours = sum(d['hours'] for d in stats['flights_by_instructor'].values())
        total_instr_flights = sum(d['count'] for d in stats['flights_by_instructor'].values())
        html.append("<div class='section'>")
        html.append("<h2>Training by Instructor</h2>")
        html.append(f"<p><strong>Total Training:</strong> {total_instr_flights} flights, {format_hours(total_instr_hours)} hours with instructors</p>")
        html.append("<table><tr><th>Instructor</th><th>Flights</th><th>Dual Hours</th></tr>")
        sorted_instr = sorted(stats['flights_by_instructor'].items(), key=lambda x: -x[1]['hours'])
        for instr, data in sorted_instr:
            html.append(f"<tr><td>{instr}</td><td>{data['count']}</td><td>{format_hours(data['hours'])}</td></tr>")
        html.append("</table></div>")

    # Airports
    html.append("<div class='two-col'>")
    html.append("<div class='section'>")
    html.append("<h2>Airports</h2>")
    html.append("<table><tr><th>Airport</th><th>Visits</th></tr>")
    sorted_airports = sorted(stats['airports'].items(), key=lambda x: -x[1])
    for airport, count in sorted_airports[:15]:
        html.append(f"<tr><td>{format_airport(airport, airports)}</td><td>{count}</td></tr>")
    html.append("</table></div>")

    # Routes
    html.append("<div class='section'>")
    html.append("<h2>Most Frequent Routes</h2>")
    html.append("<table><tr><th>Route</th><th>Flights</th></tr>")
    sorted_routes = sorted(stats['routes'].items(), key=lambda x: -x[1])
    for route, count in sorted_routes[:15]:
        parts = route.split('-')
        if len(parts) == 2:
            formatted = f"{format_airport(parts[0], airports)} - {format_airport(parts[1], airports)}"
        else:
            formatted = route
        html.append(f"<tr><td>{formatted}</td><td>{count}</td></tr>")
    html.append("</table></div>")
    html.append("</div>")

    # Recent Flights
    html.append("<div class='section'>")
    html.append("<h2>Recent Flights</h2>")
    html.append("<table><tr><th>Date</th><th>Aircraft</th><th>Route</th><th>Hours</th><th>Capacity</th></tr>")
    for f in flights[:30]:
        date = f['date'].strftime('%Y-%m-%d') if f['date'] else ''
        reg = f['registration'] or ''
        route = f"{f['dep_airport'] or ''}-{f['arr_airport'] or ''}"
        hours = format_hours(f['hours_total'] or 0) if f['hours_total'] else ''
        capacity = f['operating_capacity'] or ''
        html.append(f"<tr><td>{date}</td><td>{reg}</td><td>{route}</td><td>{hours}</td><td>{capacity}</td></tr>")
    html.append("</table></div>")

    html.append("</body></html>")

    return "\n".join(html)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate GA flight reports')
    parser.add_argument('--html', action='store_true', help='Generate HTML only')
    parser.add_argument('--md', action='store_true', help='Generate Markdown only')
    args = parser.parse_args()

    # Default to both if neither specified
    if not args.html and not args.md:
        args.html = True
        args.md = True

    # Ensure reports directory exists
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching GA flight data...")
    conn = db.get_connection()
    cur = conn.cursor()

    flights = get_all_flights(cur)
    print(f"Found {len(flights)} GA flights")

    cur.close()
    conn.close()

    if not flights:
        print("No GA flights found in database")
        return

    print("Calculating statistics...")
    stats = calculate_statistics(flights)

    # Load airport database for names
    airports = load_airports()

    if args.md:
        print("Generating markdown report...")
        md_report = generate_markdown(flights, stats, airports)
        with open(OUTPUT_MD, 'w') as f:
            f.write(md_report)
        print(f"Wrote {OUTPUT_MD}")

    if args.html:
        print("Generating HTML report...")
        html_report = generate_html(flights, stats, airports)
        with open(OUTPUT_HTML, 'w') as f:
            f.write(html_report)
        print(f"Wrote {OUTPUT_HTML}")

    print("Done!")


if __name__ == '__main__':
    main()
