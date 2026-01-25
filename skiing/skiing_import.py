#!/usr/bin/env python3
"""
Import SkiTracks GPS data to gps_points database table.

Parses Nodes.csv files from SkiTracks exports and inserts GPS points
with source_type='skitracks' and device_id='skitracks'.

Applies anomaly filtering for speed and altitude spikes.
"""

import sys
import csv
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import db

TRACKS_DIR = Path(__file__).parent.parent / "data" / "skiing" / "Tracks"

# Thresholds for anomaly detection
MAX_REALISTIC_SPEED_MS = 28.0  # ~100 km/h - reasonable max for recreational skiing
MAX_ALTITUDE_JUMP_M = 100.0    # Max altitude change per second
MAX_REALISTIC_ALTITUDE_M = 5000.0  # Higher than any European ski resort
MIN_REALISTIC_ALTITUDE_M = 500.0   # Lower limit for ski resorts


def filter_anomalous_point(point, prev_point, next_point):
    """
    Check if a GPS point is anomalous based on speed and altitude.

    Returns: True if point should be filtered out
    """
    speed = point.get('speed_ms', 0)
    altitude = point.get('altitude', 0)

    # Filter unrealistic speed
    if speed < 0 or speed > MAX_REALISTIC_SPEED_MS:
        return True

    # Filter unrealistic altitude
    if altitude < MIN_REALISTIC_ALTITUDE_M or altitude > MAX_REALISTIC_ALTITUDE_M:
        return True

    # Check for altitude spike (if we have neighbors)
    if prev_point and next_point:
        prev_alt = prev_point.get('altitude', 0)
        next_alt = next_point.get('altitude', 0)
        prev_time = prev_point.get('timestamp', 0)
        next_time = next_point.get('timestamp', 0)
        curr_time = point.get('timestamp', 0)

        dt_prev = max(curr_time - prev_time, 0.1)
        dt_next = max(next_time - curr_time, 0.1)

        alt_rate_prev = abs(altitude - prev_alt) / dt_prev
        alt_rate_next = abs(altitude - next_alt) / dt_next

        # If altitude changes too fast in both directions, it's a spike
        if alt_rate_prev > MAX_ALTITUDE_JUMP_M and alt_rate_next > MAX_ALTITUDE_JUMP_M:
            # Check if neighbors are close to each other (confirming this is an outlier)
            if abs(prev_alt - next_alt) < MAX_ALTITUDE_JUMP_M * (next_time - prev_time):
                return True

    return False


def parse_nodes_csv(nodes_path, track_id):
    """
    Parse a Nodes.csv file and return list of GPS points.

    Nodes.csv format: timestamp, lat, lon, altitude, heading, speed, h_acc, v_acc
    """
    points = []

    try:
        with open(nodes_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as e:
        print(f"  Error reading {nodes_path}: {e}")
        return []

    if len(rows) < 3:
        return []

    # Parse all points first
    raw_points = []
    for row in rows:
        if len(row) < 6:
            continue
        try:
            timestamp = float(row[0])
            lat = float(row[1])
            lon = float(row[2])
            altitude = float(row[3])
            heading = float(row[4]) if row[4] and float(row[4]) >= 0 else None
            speed_ms = float(row[5]) if row[5] else 0

            # Convert speed from m/s
            speed_kmh = speed_ms * 3.6
            speed_mph = speed_ms * 2.237

            # Convert altitude
            altitude_ft = altitude * 3.281

            raw_points.append({
                'timestamp': timestamp,
                'lat': lat,
                'lon': lon,
                'altitude': altitude,
                'heading': heading,
                'speed_ms': speed_ms,
                'speed_kmh': speed_kmh,
                'speed_mph': speed_mph,
                'altitude_ft': altitude_ft,
            })
        except (ValueError, IndexError):
            continue

    # Filter anomalous points
    for i, pt in enumerate(raw_points):
        prev_pt = raw_points[i-1] if i > 0 else None
        next_pt = raw_points[i+1] if i < len(raw_points) - 1 else None

        if filter_anomalous_point(pt, prev_pt, next_pt):
            continue

        # Convert timestamp to datetime
        ts = datetime.fromtimestamp(pt['timestamp'], tz=timezone.utc)

        points.append({
            'device_id': 'skitracks',
            'device_name': f'SkiTracks-{track_id}',
            'ts': ts,
            'lat': pt['lat'],
            'lon': pt['lon'],
            'altitude_m': pt['altitude'],
            'altitude_ft': pt['altitude_ft'],
            'speed_mph': pt['speed_mph'],
            'speed_kmh': pt['speed_kmh'],
            'direction': pt['heading'],
            'accuracy_m': None,
            'battery_pct': None,
            'source_type': 'skitracks',
        })

    return points


def import_all_tracks(dry_run=False, limit=None):
    """
    Import all SkiTracks GPS data to database.

    Args:
        dry_run: If True, parse but don't insert
        limit: Maximum number of tracks to process (for testing)
    """
    if not TRACKS_DIR.exists():
        print(f"Tracks directory not found: {TRACKS_DIR}")
        return

    track_dirs = sorted(TRACKS_DIR.glob("Track*.ski"))
    if limit:
        track_dirs = track_dirs[:limit]

    print(f"Found {len(track_dirs)} track directories")

    total_points = 0
    total_inserted = 0
    total_skipped = 0
    tracks_processed = 0

    for track_dir in track_dirs:
        nodes_path = track_dir / "Nodes.csv"
        if not nodes_path.exists():
            continue

        track_id = track_dir.name.replace('.ski', '').replace('Track', '')

        points = parse_nodes_csv(nodes_path, track_id)
        if not points:
            continue

        tracks_processed += 1
        total_points += len(points)

        if dry_run:
            # Get date range for this track
            if points:
                start_date = points[0]['ts'].strftime('%Y-%m-%d')
                print(f"  {track_dir.name}: {len(points)} points ({start_date})")
        else:
            # Insert to database
            inserted, skipped = db.insert_points(points)
            total_inserted += inserted
            total_skipped += skipped

            if inserted > 0:
                print(f"  {track_dir.name}: {inserted} inserted, {skipped} skipped")

    print(f"\nSummary:")
    print(f"  Tracks processed: {tracks_processed}")
    print(f"  Total points parsed: {total_points}")
    if not dry_run:
        print(f"  Points inserted: {total_inserted}")
        print(f"  Points skipped (duplicates): {total_skipped}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Import SkiTracks GPS data to database')
    parser.add_argument('--dry-run', action='store_true', help='Parse but do not insert')
    parser.add_argument('--limit', type=int, help='Limit number of tracks to process')
    args = parser.parse_args()

    print("Importing SkiTracks GPS data...")
    import_all_tracks(dry_run=args.dry_run, limit=args.limit)
    print("\nDone!")


if __name__ == '__main__':
    main()
