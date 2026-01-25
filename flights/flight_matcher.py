#!/usr/bin/env python3
"""
Match flight diary entries with GPS-detected flights.

Cross-references flightdiary entries with GPS-detected flights and merges
matching records into unified entries with source='merged'.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import db


def get_flights_by_source(cur, source):
    """Get all flights with a specific source."""
    cur.execute("""
        SELECT id, date, flight_number, dep_airport, arr_airport,
               dep_time, arr_time, duration, airline, airline_code,
               aircraft_type, aircraft_code, registration, seat_number,
               seat_type, flight_class, flight_reason, notes,
               dep_lat, dep_lon, arr_lat, arr_lon, distance_km
        FROM flights
        WHERE source = %s
        ORDER BY date
    """, (source,))
    return cur.fetchall()


def find_matching_gps_flight(diary_flight, gps_flights):
    """
    Find a GPS-detected flight that matches a diary entry.

    Matching criteria:
    - Same departure airport (IATA code)
    - Same arrival airport (IATA code)
    - Within +/- 1 day of diary date

    Returns: matching GPS flight row or None
    """
    diary_date = diary_flight[1]  # date is index 1
    dep_airport = diary_flight[3]  # dep_airport is index 3
    arr_airport = diary_flight[4]  # arr_airport is index 4

    for gps_flight in gps_flights:
        gps_date = gps_flight[1]
        gps_dep = gps_flight[3]
        gps_arr = gps_flight[4]

        # Check airports match
        if gps_dep != dep_airport or gps_arr != arr_airport:
            continue

        # Check date within +/- 1 day
        date_diff = abs((diary_date - gps_date).days)
        if date_diff <= 1:
            return gps_flight

    return None


def merge_flights(diary_flight, gps_flight, cur):
    """
    Merge a diary flight with a GPS flight.

    Strategy:
    - Keep all diary details (flight number, seat, airline, etc.)
    - Mark as gps_matched = TRUE
    - Update source to 'merged'
    - Delete the GPS-detected record
    """
    diary_id = diary_flight[0]
    gps_id = gps_flight[0]

    # Update diary flight to merged
    cur.execute("""
        UPDATE flights
        SET source = 'merged', gps_matched = TRUE
        WHERE id = %s
    """, (diary_id,))

    # Delete the GPS-detected duplicate
    cur.execute("DELETE FROM flights WHERE id = %s", (gps_id,))

    return diary_id


def run_matching(dry_run=False):
    """
    Run the flight matching process.

    Args:
        dry_run: If True, show what would be matched but don't update
    """
    conn = db.get_connection()
    cur = conn.cursor()

    # Get flights by source
    diary_flights = get_flights_by_source(cur, 'flightdiary')
    gps_flights = get_flights_by_source(cur, 'gps-detected')

    print(f"Flight diary entries: {len(diary_flights)}")
    print(f"GPS-detected flights: {len(gps_flights)}")

    if not diary_flights or not gps_flights:
        print("No flights to match")
        cur.close()
        conn.close()
        return

    matched = []
    unmatched_diary = []
    gps_matched_ids = set()

    for diary_flight in diary_flights:
        gps_match = find_matching_gps_flight(diary_flight, gps_flights)

        if gps_match:
            matched.append((diary_flight, gps_match))
            gps_matched_ids.add(gps_match[0])  # Track matched GPS IDs
        else:
            unmatched_diary.append(diary_flight)

    unmatched_gps = [f for f in gps_flights if f[0] not in gps_matched_ids]

    print(f"\nMatching results:")
    print(f"  Matched pairs: {len(matched)}")
    print(f"  Unmatched diary entries: {len(unmatched_diary)}")
    print(f"  Unmatched GPS flights: {len(unmatched_gps)}")

    if dry_run:
        print("\n--- DRY RUN ---")
        print("\nMatched flights (first 10):")
        for diary, gps in matched[:10]:
            print(f"  {diary[1]} {diary[3]}->{diary[4]} (diary) <-> {gps[1]} (GPS)")

        if unmatched_diary:
            print(f"\nUnmatched diary entries (first 10):")
            for f in unmatched_diary[:10]:
                print(f"  {f[1]} {f[2] or 'N/A':8} {f[3]}->{f[4]}")

        if unmatched_gps:
            print(f"\nUnmatched GPS flights (first 10):")
            for f in unmatched_gps[:10]:
                print(f"  {f[1]} {f[3]}->{f[4]}")

        cur.close()
        conn.close()
        return

    # Perform the merge
    print("\nMerging matched flights...")
    for diary_flight, gps_flight in matched:
        merge_flights(diary_flight, gps_flight, cur)

    conn.commit()

    # Verify results
    cur.execute("SELECT source, COUNT(*) FROM flights GROUP BY source ORDER BY source")
    counts = cur.fetchall()
    print("\nFlight counts by source:")
    for source, count in counts:
        print(f"  {source}: {count}")

    cur.close()
    conn.close()

    print("\nMatching complete!")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Match flight diary with GPS flights')
    parser.add_argument('--dry-run', action='store_true', help='Show matches without updating')
    args = parser.parse_args()

    run_matching(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
