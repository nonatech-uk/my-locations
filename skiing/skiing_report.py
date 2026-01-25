#!/usr/bin/env python3
"""
Generate skiing analysis reports from the skiing_days database table.

Outputs:
- ~/skiing_report.html - Interactive HTML report
- ~/skiing_report.md - Markdown summary
"""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import db

REPORTS_DIR = Path(__file__).parent.parent / "reports"
OUTPUT_HTML = REPORTS_DIR / "skiing_report.html"
OUTPUT_MD = REPORTS_DIR / "skiing_report.md"


def get_all_skiing_days(cur):
    """Get all skiing days from database."""
    cur.execute("""
        SELECT date, location, duration_hours, distance_km,
               vertical_up_m, vertical_down_m, max_speed_kmh, avg_speed_kmh,
               max_altitude_m, min_altitude_m, num_runs, num_lifts,
               platform, season
        FROM skiing_days
        WHERE date IS NOT NULL
        ORDER BY date DESC
    """)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def calculate_statistics(days):
    """Calculate comprehensive skiing statistics."""
    stats = {
        'total_days': len(days),
        'total_distance_km': sum(float(d['distance_km'] or 0) for d in days),
        'total_vertical_down': sum(int(d['vertical_down_m'] or 0) for d in days),
        'total_vertical_up': sum(int(d['vertical_up_m'] or 0) for d in days),
        'total_duration_hours': sum(float(d['duration_hours'] or 0) for d in days),
        'total_runs': sum(int(d['num_runs'] or 0) for d in days),
        'total_lifts': sum(int(d['num_lifts'] or 0) for d in days),
        'days_by_season': defaultdict(list),
        'days_by_location': defaultdict(int),
        'records': {},
    }

    for d in days:
        # Season stats
        if d['season']:
            stats['days_by_season'][d['season']].append(d)

        # Location stats
        location = d['location'] or 'Unknown'
        stats['days_by_location'][location] += 1

    # Find records (only from days with valid data)
    valid_speed = [d for d in days if d['max_speed_kmh'] and d['max_speed_kmh'] > 0]
    valid_vertical = [d for d in days if d['vertical_down_m'] and d['vertical_down_m'] > 0]
    valid_distance = [d for d in days if d['distance_km'] and d['distance_km'] > 0]
    valid_altitude = [d for d in days if d['max_altitude_m'] and d['max_altitude_m'] > 0]
    valid_runs = [d for d in days if d['num_runs'] and d['num_runs'] > 0]

    if valid_speed:
        stats['records']['max_speed'] = max(valid_speed, key=lambda x: x['max_speed_kmh'])
    if valid_vertical:
        stats['records']['max_vertical'] = max(valid_vertical, key=lambda x: x['vertical_down_m'])
    if valid_distance:
        stats['records']['max_distance'] = max(valid_distance, key=lambda x: x['distance_km'])
    if valid_altitude:
        stats['records']['max_altitude'] = max(valid_altitude, key=lambda x: x['max_altitude_m'])
    if valid_runs:
        stats['records']['max_runs'] = max(valid_runs, key=lambda x: x['num_runs'])

    return stats


def format_date(d):
    """Format a date for display."""
    if isinstance(d, str):
        return d
    return d.strftime('%Y-%m-%d') if d else ''


def generate_markdown(days, stats):
    """Generate markdown report."""
    lines = []
    lines.append("# Skiing Activity Report")
    lines.append("")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    # Date range
    if days:
        dates = [d['date'] for d in days if d['date']]
        if dates:
            lines.append(f"**Date Range:** {format_date(min(dates))} to {format_date(max(dates))}")
            lines.append("")

    # Overall statistics
    lines.append("## Overall Statistics")
    lines.append("")
    lines.append(f"- **Total Ski Days:** {stats['total_days']}")
    lines.append(f"- **Total Distance:** {stats['total_distance_km']:,.1f} km")
    lines.append(f"- **Total Vertical Descent:** {stats['total_vertical_down']:,} m ({stats['total_vertical_down']/1000:,.1f} km)")
    lines.append(f"- **Total Vertical Ascent:** {stats['total_vertical_up']:,} m ({stats['total_vertical_up']/1000:,.1f} km)")
    lines.append(f"- **Total Time on Mountain:** {stats['total_duration_hours']:,.1f} hours ({stats['total_duration_hours']/24:,.1f} days)")
    lines.append(f"- **Total Ski Runs:** {stats['total_runs']:,}")
    lines.append(f"- **Total Lift Rides:** {stats['total_lifts']:,}")
    lines.append("")

    # Personal Records
    if stats['records']:
        lines.append("## Personal Records")
        lines.append("")
        if 'max_speed' in stats['records']:
            r = stats['records']['max_speed']
            lines.append(f"- **Fastest Speed:** {r['max_speed_kmh']:.1f} km/h at {r['location']} ({format_date(r['date'])})")
        if 'max_vertical' in stats['records']:
            r = stats['records']['max_vertical']
            lines.append(f"- **Most Vertical in a Day:** {r['vertical_down_m']:,} m at {r['location']} ({format_date(r['date'])})")
        if 'max_distance' in stats['records']:
            r = stats['records']['max_distance']
            lines.append(f"- **Longest Distance in a Day:** {r['distance_km']:.1f} km at {r['location']} ({format_date(r['date'])})")
        if 'max_altitude' in stats['records']:
            r = stats['records']['max_altitude']
            lines.append(f"- **Highest Altitude:** {r['max_altitude_m']:,} m at {r['location']} ({format_date(r['date'])})")
        if 'max_runs' in stats['records']:
            r = stats['records']['max_runs']
            lines.append(f"- **Most Runs in a Day:** {r['num_runs']} at {r['location']} ({format_date(r['date'])})")
        lines.append("")

    # Season Breakdown
    if stats['days_by_season']:
        lines.append("## Season Breakdown")
        lines.append("")
        lines.append("| Season | Days | Distance (km) | Vertical (m) | Runs |")
        lines.append("|--------|------|---------------|--------------|------|")

        for season in sorted(stats['days_by_season'].keys()):
            season_days = stats['days_by_season'][season]
            num_days = len(season_days)
            distance = sum(float(d['distance_km'] or 0) for d in season_days)
            vertical = sum(int(d['vertical_down_m'] or 0) for d in season_days)
            runs = sum(int(d['num_runs'] or 0) for d in season_days)
            lines.append(f"| {season} | {num_days} | {distance:,.1f} | {vertical:,} | {runs} |")
        lines.append("")

    # Resorts Visited
    if stats['days_by_location']:
        lines.append("## Resorts Visited")
        lines.append("")
        sorted_locations = sorted(stats['days_by_location'].items(), key=lambda x: (-x[1], x[0]))
        for location, count in sorted_locations:
            lines.append(f"- **{location}**: {count} day{'s' if count != 1 else ''}")
        lines.append("")

    return "\n".join(lines)


def generate_html(days, stats):
    """Generate interactive HTML report."""
    html = []
    html.append("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Skiing Report</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%);
            color: #333;
            min-height: 100vh;
        }
        h1 { color: #0369a1; border-bottom: 3px solid #0369a1; padding-bottom: 10px; }
        h2 { color: #0c4a6e; margin-top: 30px; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
            border-left: 4px solid #0369a1;
        }
        .stat-card .number {
            font-size: 2em;
            font-weight: bold;
            color: #0369a1;
        }
        .stat-card .label {
            color: #64748b;
            font-size: 0.9em;
            margin-top: 5px;
        }
        .record-card {
            background: linear-gradient(135deg, #fef3c7 0%, #fef9c3 100%);
            border-left-color: #d97706;
        }
        .record-card .number { color: #b45309; }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin: 15px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        th {
            background: #f1f5f9;
            font-weight: 600;
            color: #475569;
        }
        tr:hover { background: #f8fafc; }
        .section { margin-bottom: 40px; }
        .generated {
            color: #64748b;
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

    html.append(f"<h1>Skiing Activity Report</h1>")
    html.append(f"<p class='generated'>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>")

    # Stats cards
    html.append("<div class='stats-grid'>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_days']}</div><div class='label'>Ski Days</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_distance_km']:,.0f}</div><div class='label'>Total KM</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_vertical_down']/1000:,.0f}</div><div class='label'>Vertical KM</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_duration_hours']:,.0f}</div><div class='label'>Hours</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_runs']:,}</div><div class='label'>Runs</div></div>")
    html.append(f"<div class='stat-card'><div class='number'>{stats['total_lifts']:,}</div><div class='label'>Lifts</div></div>")
    html.append("</div>")

    # Personal Records
    if stats['records']:
        html.append("<h2>Personal Records</h2>")
        html.append("<div class='stats-grid'>")
        if 'max_speed' in stats['records']:
            r = stats['records']['max_speed']
            html.append(f"<div class='stat-card record-card'><div class='number'>{r['max_speed_kmh']:.1f}</div><div class='label'>Max Speed (km/h)<br>{r['location']}</div></div>")
        if 'max_vertical' in stats['records']:
            r = stats['records']['max_vertical']
            html.append(f"<div class='stat-card record-card'><div class='number'>{r['vertical_down_m']:,}</div><div class='label'>Max Vertical (m)<br>{r['location']}</div></div>")
        if 'max_altitude' in stats['records']:
            r = stats['records']['max_altitude']
            html.append(f"<div class='stat-card record-card'><div class='number'>{r['max_altitude_m']:,}</div><div class='label'>Highest Altitude (m)<br>{r['location']}</div></div>")
        if 'max_runs' in stats['records']:
            r = stats['records']['max_runs']
            html.append(f"<div class='stat-card record-card'><div class='number'>{r['num_runs']}</div><div class='label'>Most Runs (1 day)<br>{r['location']}</div></div>")
        html.append("</div>")

    # Season breakdown
    if stats['days_by_season']:
        html.append("<div class='section'>")
        html.append("<h2>Season Breakdown</h2>")
        html.append("<table><tr><th>Season</th><th>Days</th><th>Distance</th><th>Vertical</th><th>Runs</th></tr>")
        for season in sorted(stats['days_by_season'].keys(), reverse=True):
            season_days = stats['days_by_season'][season]
            num_days = len(season_days)
            distance = sum(float(d['distance_km'] or 0) for d in season_days)
            vertical = sum(int(d['vertical_down_m'] or 0) for d in season_days)
            runs = sum(int(d['num_runs'] or 0) for d in season_days)
            html.append(f"<tr><td>{season}</td><td>{num_days}</td><td>{distance:,.0f} km</td><td>{vertical:,} m</td><td>{runs}</td></tr>")
        html.append("</table></div>")

    # Resorts
    if stats['days_by_location']:
        html.append("<div class='section'>")
        html.append("<h2>Resorts Visited</h2>")
        html.append("<table><tr><th>Resort</th><th>Days</th></tr>")
        sorted_locations = sorted(stats['days_by_location'].items(), key=lambda x: (-x[1], x[0]))
        for location, count in sorted_locations[:20]:
            html.append(f"<tr><td>{location}</td><td>{count}</td></tr>")
        html.append("</table></div>")

    # Recent days
    html.append("<div class='section'>")
    html.append("<h2>Recent Ski Days</h2>")
    html.append("<table><tr><th>Date</th><th>Location</th><th>Distance</th><th>Vertical</th><th>Max Speed</th><th>Runs</th></tr>")
    for d in days[:30]:
        date = format_date(d['date'])
        location = d['location'] or 'Unknown'
        distance = f"{d['distance_km']:.1f} km" if d['distance_km'] else '-'
        vertical = f"{d['vertical_down_m']:,} m" if d['vertical_down_m'] else '-'
        speed = f"{d['max_speed_kmh']:.1f} km/h" if d['max_speed_kmh'] else '-'
        runs = d['num_runs'] or '-'
        html.append(f"<tr><td>{date}</td><td>{location}</td><td>{distance}</td><td>{vertical}</td><td>{speed}</td><td>{runs}</td></tr>")
    html.append("</table></div>")

    html.append("</body></html>")

    return "\n".join(html)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Generate skiing reports')
    parser.add_argument('--html', action='store_true', help='Generate HTML only')
    parser.add_argument('--md', action='store_true', help='Generate Markdown only')
    args = parser.parse_args()

    # Default to both if neither specified
    if not args.html and not args.md:
        args.html = True
        args.md = True

    print("Fetching skiing data...")
    conn = db.get_connection()
    cur = conn.cursor()

    days = get_all_skiing_days(cur)
    print(f"Found {len(days)} skiing days")

    cur.close()
    conn.close()

    if not days:
        print("No skiing days found in database")
        return

    print("Calculating statistics...")
    stats = calculate_statistics(days)

    if args.md:
        print(f"Generating markdown report...")
        md_report = generate_markdown(days, stats)
        with open(OUTPUT_MD, 'w') as f:
            f.write(md_report)
        print(f"Wrote {OUTPUT_MD}")

    if args.html:
        print(f"Generating HTML report...")
        html_report = generate_html(days, stats)
        with open(OUTPUT_HTML, 'w') as f:
            f.write(html_report)
        print(f"Wrote {OUTPUT_HTML}")

    print("Done!")


if __name__ == '__main__':
    main()
