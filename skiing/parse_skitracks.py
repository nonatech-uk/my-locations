#!/usr/bin/env python3
"""
Parse SkiTracks exports and generate skiing activity records.
Filters anomalous GPS points to get accurate max speed and altitude.
Optionally imports to database skiing_days table.
"""

import os
import csv
import sys
import math
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


DATA_DIR = Path(__file__).parent.parent / "data" / "skiing"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
TRACKS_DIR = DATA_DIR / "Tracks"
OUTPUT_CSV = DATA_DIR / "skiing_record.csv"
OUTPUT_MD = REPORTS_DIR / "skiing_summary.md"

# Thresholds for anomaly detection
MAX_REALISTIC_SPEED_MS = 28.0  # ~100 km/h - reasonable max for recreational skiing
MAX_ALTITUDE_JUMP_M = 100.0    # Max altitude change per second
MAX_REALISTIC_ALTITUDE_M = 5000.0  # Higher than any European ski resort
MIN_REALISTIC_ALTITUDE_M = 500.0   # Lower limit for ski resorts


def parse_nodes_csv(nodes_path):
    """
    Parse Nodes.csv and return filtered max speed and altitude range.
    Filters out anomalous GPS points that jump and snap back.

    Returns: (max_speed_ms, max_altitude_m, min_altitude_m) or None if can't parse
    """
    if not nodes_path.exists():
        return None

    try:
        with open(nodes_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None

    if len(rows) < 3:
        return None

    # Parse points: timestamp, lat, lon, altitude, heading, speed, h_acc, v_acc
    points = []
    for row in rows:
        if len(row) < 6:
            continue
        try:
            timestamp = float(row[0])
            altitude = float(row[3])
            speed = float(row[5])
            points.append({
                'time': timestamp,
                'alt': altitude,
                'speed': speed
            })
        except (ValueError, IndexError):
            continue

    if len(points) < 3:
        return None

    # Filter anomalous points using a sliding window approach
    # A point is anomalous if it jumps away and then snaps back
    filtered_speeds = []
    filtered_altitudes = []

    for i, pt in enumerate(points):
        # Check if speed is realistic
        if pt['speed'] < 0 or pt['speed'] > MAX_REALISTIC_SPEED_MS:
            continue

        # Check if altitude is realistic
        if pt['alt'] < MIN_REALISTIC_ALTITUDE_M or pt['alt'] > MAX_REALISTIC_ALTITUDE_M:
            continue

        # Check for altitude jumps relative to neighbors
        is_altitude_spike = False
        if i > 0 and i < len(points) - 1:
            prev_alt = points[i-1]['alt']
            next_alt = points[i+1]['alt']
            curr_alt = pt['alt']

            prev_time = points[i-1]['time']
            next_time = points[i+1]['time']
            curr_time = pt['time']

            # Check if this point is a spike (jumps away from both neighbors)
            dt_prev = max(curr_time - prev_time, 0.1)
            dt_next = max(next_time - curr_time, 0.1)

            alt_rate_prev = abs(curr_alt - prev_alt) / dt_prev
            alt_rate_next = abs(curr_alt - next_alt) / dt_next

            # If altitude changes too fast in both directions, it's a spike
            if alt_rate_prev > MAX_ALTITUDE_JUMP_M and alt_rate_next > MAX_ALTITUDE_JUMP_M:
                # Check if neighbors are close to each other (confirming this is an outlier)
                if abs(prev_alt - next_alt) < MAX_ALTITUDE_JUMP_M * (next_time - prev_time):
                    is_altitude_spike = True

        if not is_altitude_spike:
            filtered_speeds.append(pt['speed'])
            filtered_altitudes.append(pt['alt'])

    if not filtered_speeds or not filtered_altitudes:
        return None

    return (
        max(filtered_speeds),
        max(filtered_altitudes),
        min(filtered_altitudes)
    )


def parse_track_xml(xml_path):
    """Parse Track.xml and extract metadata and metrics."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Check if hidden
    if root.get("hidden") == "true":
        return None

    # Extract basic attributes
    data = {
        "name": root.get("name", ""),
        "location": root.get("description", "Unknown"),
        "start": root.get("start", ""),
        "finish": root.get("finish", ""),
        "duration_seconds": float(root.get("duration", 0)),
        "platform": root.get("platform", "Unknown"),
    }

    # Parse start date
    if data["start"]:
        # Handle ISO8601 format with timezone
        start_str = data["start"]
        # Remove the timezone part for parsing
        if "+" in start_str:
            start_str = start_str.split("+")[0]
        elif start_str.endswith("Z"):
            start_str = start_str[:-1]
        try:
            data["date"] = datetime.fromisoformat(start_str).date()
        except ValueError:
            data["date"] = None
    else:
        data["date"] = None

    # Extract metrics
    metrics = root.find("metrics")
    if metrics is not None:
        data["max_speed_ms"] = float(metrics.findtext("maxspeed", 0))
        data["avg_speed_ms"] = float(metrics.findtext("averagespeed", 0))
        data["total_ascent"] = float(metrics.findtext("totalascent", 0))
        data["total_descent"] = float(metrics.findtext("totaldescent", 0))
        data["max_altitude"] = float(metrics.findtext("maxaltitude", 0))
        data["min_altitude"] = float(metrics.findtext("minaltitude", 0))
        data["distance_m"] = float(metrics.findtext("distance", 0))
        data["num_lifts"] = int(metrics.findtext("ascents", 0))
        data["num_runs"] = int(metrics.findtext("descents", 0))
    else:
        data["max_speed_ms"] = 0
        data["avg_speed_ms"] = 0
        data["total_ascent"] = 0
        data["total_descent"] = 0
        data["max_altitude"] = 0
        data["min_altitude"] = 0
        data["distance_m"] = 0
        data["num_lifts"] = 0
        data["num_runs"] = 0

    return data


def get_ski_season(date):
    """Determine ski season from a date (e.g., 2023/2024)."""
    if date is None:
        return "Unknown"

    month = date.month
    year = date.year

    # Ski season spans Nov-Apr
    # Nov, Dec = use current year as start
    # Jan-Apr = use previous year as start
    # May-Oct = edge case, use current year as start (early season)
    if month >= 11:
        return f"{year}/{year + 1}"
    elif month <= 4:
        return f"{year - 1}/{year}"
    else:
        # May-Oct skiing (rare, summer skiing)
        return f"{year}/{year + 1}"


def simplify_platform(platform):
    """Extract device type from platform string."""
    if not platform or platform == "Unknown":
        return "Unknown"

    platform_lower = platform.lower()
    if "watch" in platform_lower:
        return "Apple Watch"
    elif "iphone" in platform_lower:
        return "iPhone"
    elif "ipad" in platform_lower:
        return "iPad"
    else:
        return "Unknown"


def parse_all_tracks():
    """Parse all track directories and return list of track data."""
    tracks = []

    for track_dir in sorted(TRACKS_DIR.glob("Track*.ski")):
        xml_path = track_dir / "Track.xml"
        if not xml_path.exists():
            continue

        try:
            data = parse_track_xml(xml_path)
            if data is None:  # Hidden track
                continue

            # Get filtered max speed and altitude from raw GPS data
            nodes_path = track_dir / "Nodes.csv"
            filtered = parse_nodes_csv(nodes_path)

            if filtered:
                max_speed_ms, max_alt, min_alt = filtered
            else:
                # Fall back to XML values if can't parse nodes
                max_speed_ms = data["max_speed_ms"]
                max_alt = data["max_altitude"]
                min_alt = data["min_altitude"]

            # Convert units
            track = {
                "date": data["date"].isoformat() if data["date"] else "",
                "location": data["location"],
                "duration_hours": round(data["duration_seconds"] / 3600, 2),
                "distance_km": round(data["distance_m"] / 1000, 2),
                "vertical_up_m": round(data["total_ascent"], 0),
                "vertical_down_m": round(data["total_descent"], 0),
                "max_speed_kmh": round(max_speed_ms * 3.6, 1),
                "avg_speed_kmh": round(data["avg_speed_ms"] * 3.6, 1),
                "max_altitude_m": round(max_alt, 0),
                "min_altitude_m": round(min_alt, 0),
                "num_runs": data["num_runs"],
                "num_lifts": data["num_lifts"],
                "platform": simplify_platform(data["platform"]),
                "season": get_ski_season(data["date"]),
            }
            tracks.append(track)
        except Exception as e:
            print(f"Error parsing {track_dir}: {e}")

    return tracks


def write_csv(tracks):
    """Write tracks to CSV file."""
    fieldnames = [
        "date", "location", "duration_hours", "distance_km",
        "vertical_up_m", "vertical_down_m", "max_speed_kmh", "avg_speed_kmh",
        "max_altitude_m", "min_altitude_m", "num_runs", "num_lifts",
        "platform", "season"
    ]

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(tracks, key=lambda x: x["date"]))

    print(f"Wrote {len(tracks)} tracks to {OUTPUT_CSV}")


def generate_summary(tracks):
    """Generate markdown summary of skiing activity."""
    if not tracks:
        return "No tracks found."

    # Sort by date
    sorted_tracks = sorted(tracks, key=lambda x: x["date"])

    # Calculate totals
    total_days = len(tracks)
    total_distance = sum(t["distance_km"] for t in tracks)
    total_vertical_down = sum(t["vertical_down_m"] for t in tracks)
    total_vertical_up = sum(t["vertical_up_m"] for t in tracks)
    total_duration = sum(t["duration_hours"] for t in tracks)
    total_runs = sum(t["num_runs"] for t in tracks)
    total_lifts = sum(t["num_lifts"] for t in tracks)

    # Find records
    max_speed_track = max(tracks, key=lambda x: x["max_speed_kmh"])
    max_vertical_track = max(tracks, key=lambda x: x["vertical_down_m"])
    max_distance_track = max(tracks, key=lambda x: x["distance_km"])
    max_altitude_track = max(tracks, key=lambda x: x["max_altitude_m"])
    max_runs_track = max(tracks, key=lambda x: x["num_runs"])

    # Group by season
    seasons = defaultdict(list)
    for t in tracks:
        seasons[t["season"]].append(t)

    # Group by location
    locations = defaultdict(int)
    for t in tracks:
        locations[t["location"]] += 1

    # Date range (filter out tracks with empty dates)
    tracks_with_dates = [t for t in sorted_tracks if t["date"]]
    first_date = tracks_with_dates[0]["date"] if tracks_with_dates else "Unknown"
    last_date = tracks_with_dates[-1]["date"] if tracks_with_dates else "Unknown"

    # Build markdown
    md = []
    md.append("# Skiing Activity Record")
    md.append("")
    md.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    md.append("")

    md.append("## Overall Statistics")
    md.append("")
    md.append(f"- **Date Range:** {first_date} to {last_date}")
    md.append(f"- **Total Ski Days:** {total_days}")
    md.append(f"- **Total Distance:** {total_distance:,.1f} km")
    md.append(f"- **Total Vertical Descent:** {total_vertical_down:,.0f} m ({total_vertical_down/1000:,.1f} km)")
    md.append(f"- **Total Vertical Ascent:** {total_vertical_up:,.0f} m ({total_vertical_up/1000:,.1f} km)")
    md.append(f"- **Total Time on Mountain:** {total_duration:,.1f} hours ({total_duration/24:,.1f} days)")
    md.append(f"- **Total Ski Runs:** {total_runs}")
    md.append(f"- **Total Lift Rides:** {total_lifts}")
    md.append("")

    md.append("## Personal Records")
    md.append("")
    md.append(f"- **Fastest Speed:** {max_speed_track['max_speed_kmh']:.1f} km/h at {max_speed_track['location']} ({max_speed_track['date']})")
    md.append(f"- **Most Vertical in a Day:** {max_vertical_track['vertical_down_m']:,.0f} m at {max_vertical_track['location']} ({max_vertical_track['date']})")
    md.append(f"- **Longest Distance in a Day:** {max_distance_track['distance_km']:.1f} km at {max_distance_track['location']} ({max_distance_track['date']})")
    md.append(f"- **Highest Altitude:** {max_altitude_track['max_altitude_m']:,.0f} m at {max_altitude_track['location']} ({max_altitude_track['date']})")
    md.append(f"- **Most Runs in a Day:** {max_runs_track['num_runs']} at {max_runs_track['location']} ({max_runs_track['date']})")
    md.append("")

    md.append("## Season Breakdown")
    md.append("")
    md.append("| Season | Days | Distance (km) | Vertical (m) | Runs |")
    md.append("|--------|------|---------------|--------------|------|")

    for season in sorted(seasons.keys()):
        season_tracks = seasons[season]
        days = len(season_tracks)
        distance = sum(t["distance_km"] for t in season_tracks)
        vertical = sum(t["vertical_down_m"] for t in season_tracks)
        runs = sum(t["num_runs"] for t in season_tracks)
        md.append(f"| {season} | {days} | {distance:,.1f} | {vertical:,.0f} | {runs} |")

    md.append("")

    md.append("## Resorts Visited")
    md.append("")
    sorted_locations = sorted(locations.items(), key=lambda x: (-x[1], x[0]))
    for location, count in sorted_locations:
        md.append(f"- **{location}**: {count} day{'s' if count > 1 else ''}")

    md.append("")

    return "\n".join(md)


def import_to_database(tracks, dry_run=False):
    """Import skiing day records to database."""
    import db

    if not tracks:
        print("No tracks to import")
        return

    print(f"\nImporting {len(tracks)} skiing days to database...")

    if dry_run:
        print("(Dry run - not actually inserting)")
        for t in tracks[:5]:
            print(f"  {t['date']} {t['location']}: {t['vertical_down_m']}m vertical, {t['max_speed_kmh']} km/h max")
        if len(tracks) > 5:
            print(f"  ... and {len(tracks) - 5} more")
        return

    conn = db.get_connection()
    cur = conn.cursor()

    sql = """
        INSERT INTO skiing_days (
            date, location, duration_hours, distance_km,
            vertical_up_m, vertical_down_m, max_speed_kmh, avg_speed_kmh,
            max_altitude_m, min_altitude_m, num_runs, num_lifts,
            platform, season
        ) VALUES (
            %(date)s, %(location)s, %(duration_hours)s, %(distance_km)s,
            %(vertical_up_m)s, %(vertical_down_m)s, %(max_speed_kmh)s, %(avg_speed_kmh)s,
            %(max_altitude_m)s, %(min_altitude_m)s, %(num_runs)s, %(num_lifts)s,
            %(platform)s, %(season)s
        )
        ON CONFLICT (date) DO UPDATE SET
            location = EXCLUDED.location,
            duration_hours = EXCLUDED.duration_hours,
            distance_km = EXCLUDED.distance_km,
            vertical_up_m = EXCLUDED.vertical_up_m,
            vertical_down_m = EXCLUDED.vertical_down_m,
            max_speed_kmh = EXCLUDED.max_speed_kmh,
            avg_speed_kmh = EXCLUDED.avg_speed_kmh,
            max_altitude_m = EXCLUDED.max_altitude_m,
            min_altitude_m = EXCLUDED.min_altitude_m,
            num_runs = EXCLUDED.num_runs,
            num_lifts = EXCLUDED.num_lifts,
            platform = EXCLUDED.platform,
            season = EXCLUDED.season
    """

    inserted = 0
    errors = 0

    for track in tracks:
        # Skip tracks without valid dates
        if not track['date']:
            continue

        row = {
            'date': track['date'],
            'location': track['location'],
            'duration_hours': track['duration_hours'],
            'distance_km': track['distance_km'],
            'vertical_up_m': int(track['vertical_up_m']),
            'vertical_down_m': int(track['vertical_down_m']),
            'max_speed_kmh': track['max_speed_kmh'],
            'avg_speed_kmh': track['avg_speed_kmh'],
            'max_altitude_m': int(track['max_altitude_m']),
            'min_altitude_m': int(track['min_altitude_m']),
            'num_runs': track['num_runs'],
            'num_lifts': track['num_lifts'],
            'platform': track['platform'],
            'season': track['season'],
        }

        try:
            cur.execute(sql, row)
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"Error inserting {track['date']} {track['location']}: {e}")
            errors += 1
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    conn.close()

    print(f"Inserted/updated {inserted} skiing days, {errors} errors")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Parse SkiTracks exports')
    parser.add_argument('--no-csv', action='store_true', help='Skip CSV output')
    parser.add_argument('--no-md', action='store_true', help='Skip markdown output')
    parser.add_argument('--import-db', action='store_true', help='Import to database')
    parser.add_argument('--dry-run', action='store_true', help='Dry run for database import')
    args = parser.parse_args()

    print("Parsing SkiTracks exports...")
    tracks = parse_all_tracks()
    print(f"Found {len(tracks)} valid tracks")

    if not args.no_csv:
        print("\nWriting CSV...")
        write_csv(tracks)

    if not args.no_md:
        print("\nGenerating summary...")
        summary = generate_summary(tracks)
        with open(OUTPUT_MD, "w") as f:
            f.write(summary)
        print(f"Wrote summary to {OUTPUT_MD}")

    if args.import_db:
        import_to_database(tracks, dry_run=args.dry_run)

    print("\nDone!")


if __name__ == "__main__":
    main()
