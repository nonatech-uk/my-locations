#!/usr/bin/env python3
"""Sync GPS points from FollowMee API to the database."""

import argparse
import time
from datetime import datetime, timedelta

import requests

import config
import db

API_BASE = "https://followmee.com/api/tracks.aspx"
REQUEST_DELAY = 61  # Seconds between API requests (rate limit: 1/min)


def fetch_date_range(from_date, to_date):
    """Fetch GPS points for a date range."""
    params = {
        'key': config.FOLLOWMEE_API_KEY,
        'username': config.FOLLOWMEE_USERNAME,
        'output': 'json',
        'function': 'daterangefordevice',
        'deviceid': config.FOLLOWMEE_DEVICE_ID,
        'from': from_date.strftime('%Y-%m-%d'),
        'to': to_date.strftime('%Y-%m-%d'),
    }

    response = requests.get(API_BASE, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if 'Error' in data:
        raise Exception(f"API error: {data['Error']}")

    return data.get('Data', [])


def fetch_history_hours(hours):
    """Fetch GPS points for the past N hours."""
    params = {
        'key': config.FOLLOWMEE_API_KEY,
        'username': config.FOLLOWMEE_USERNAME,
        'output': 'json',
        'function': 'historyfordevice',
        'deviceid': config.FOLLOWMEE_DEVICE_ID,
        'history': hours,
    }

    response = requests.get(API_BASE, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if 'Error' in data:
        raise Exception(f"API error: {data['Error']}")

    return data.get('Data', [])


def parse_battery(battery_str):
    """Parse battery percentage from string like '85%'."""
    if not battery_str:
        return None
    try:
        return float(battery_str.rstrip('%'))
    except (ValueError, AttributeError):
        return None


def api_point_to_db(point):
    """Convert API response point to database format."""
    return {
        'device_id': config.DEVICE_ID,
        'device_name': point.get('DeviceName'),
        'ts': point.get('Date'),
        'lat': point.get('Latitude'),
        'lon': point.get('Longitude'),
        'altitude_m': point.get('Altitude(m)'),
        'altitude_ft': point.get('Altitude(ft)'),
        'speed_mph': point.get('Speed(mph)'),
        'speed_kmh': point.get('Speed(km/h)'),
        'direction': point.get('Direction'),
        'accuracy_m': point.get('Accuracy'),
        'battery_pct': parse_battery(point.get('Battery')),
        'source_type': 'followmee-api'
    }


def backfill(days=45, chunk_days=3):
    """Backfill the last N days of data in chunks."""
    db.ensure_unique_constraint()

    today = datetime.now().date()
    total_inserted = 0
    total_skipped = 0

    # Work backwards from today
    end_date = today
    chunks_processed = 0

    while (today - end_date).days < days:
        start_date = end_date - timedelta(days=chunk_days - 1)

        # Don't go further back than the backfill period
        earliest = today - timedelta(days=days)
        if start_date < earliest:
            start_date = earliest

        print(f"Fetching {start_date} to {end_date}...", end=' ', flush=True)

        try:
            points = fetch_date_range(start_date, end_date)
            if points:
                db_points = [api_point_to_db(p) for p in points]
                inserted, skipped = db.insert_points(db_points)
                total_inserted += inserted
                total_skipped += skipped
                print(f"{len(points)} points, {inserted} inserted, {skipped} duplicates")
            else:
                print("no points")

        except Exception as e:
            print(f"error: {e}")

        # Move to next chunk
        end_date = start_date - timedelta(days=1)
        chunks_processed += 1

        # Rate limiting (skip delay on last chunk)
        if (today - end_date).days < days:
            print(f"  (waiting {REQUEST_DELAY}s for rate limit...)")
            time.sleep(REQUEST_DELAY)

    print(f"\nBackfill complete: {total_inserted} inserted, {total_skipped} duplicates")


def check_gaps(lookback_days=7):
    """Check for days with no data in the last N days."""
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT d::date as day
        FROM generate_series(
            CURRENT_DATE - INTERVAL '%s days',
            CURRENT_DATE - INTERVAL '1 day',
            '1 day'::interval
        ) d
        WHERE NOT EXISTS (
            SELECT 1 FROM gps_points
            WHERE ts::date = d::date
        )
        ORDER BY d
    """, (lookback_days,))

    gaps = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return gaps


def daily_sync():
    """Sync the last 48 hours of data, then check for and fill any gaps."""
    db.ensure_unique_constraint()

    # First, sync last 48 hours
    print(f"Syncing last 48 hours...", end=' ', flush=True)

    try:
        points = fetch_history_hours(48)
        if points:
            db_points = [api_point_to_db(p) for p in points]
            inserted, skipped = db.insert_points(db_points)
            print(f"{len(points)} points, {inserted} new, {skipped} existing")
        else:
            print("no points")

    except Exception as e:
        print(f"error: {e}")

    # Check for gaps in last 7 days
    print("Checking for gaps in last 7 days...", end=' ', flush=True)
    gaps = check_gaps(lookback_days=7)

    if not gaps:
        print("none found")
        return

    print(f"found {len(gaps)} days with no data")

    # Fill gaps (within API's 45-day limit)
    for gap_date in gaps:
        print(f"  Filling {gap_date}...", end=' ', flush=True)
        time.sleep(REQUEST_DELAY)  # Rate limit

        try:
            points = fetch_date_range(gap_date, gap_date)
            if points:
                db_points = [api_point_to_db(p) for p in points]
                inserted, skipped = db.insert_points(db_points)
                print(f"{len(points)} points, {inserted} new")
            else:
                print("no data (may be genuine gap)")
        except Exception as e:
            print(f"error: {e}")


def main():
    parser = argparse.ArgumentParser(description='Sync FollowMee GPS data')
    parser.add_argument('--backfill', type=int, metavar='DAYS',
                        help='Backfill the last N days (default: 45)')
    parser.add_argument('--daily', action='store_true',
                        help='Run daily sync (last 48 hours)')

    args = parser.parse_args()

    if args.backfill:
        backfill(days=args.backfill)
    elif args.daily:
        daily_sync()
    else:
        # Default: daily sync
        daily_sync()


if __name__ == '__main__':
    main()
