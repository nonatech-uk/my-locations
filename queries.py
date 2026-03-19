"""
Canonical database queries for the my-locations system.

This module extracts the core read-only query patterns that are used across
the application (reports, visualizations, analysis scripts). A separate
project (e.g. an MCP server) can import these functions to access the same
data without duplicating SQL or business logic.

All functions take a psycopg2 cursor or connection and return plain Python
data structures (lists of dicts/tuples). No function modifies the database.

Dependencies:
    - psycopg2 (for database access)
    - A PostgreSQL database with PostGIS (for spatial queries in gps_points)

Usage:
    import db
    import queries

    conn = db.get_connection()
    cur = conn.cursor()

    flights = queries.get_all_flights(cur)
    clusters = queries.get_location_clusters(conn)

    cur.close()
    conn.close()
"""

import math
from datetime import timedelta


# ---------------------------------------------------------------------------
# GPS / Location queries
# ---------------------------------------------------------------------------

def get_location_clusters(conn, limit=200, min_hours=3):
    """
    Identify places where the user has spent significant time.

    Uses PostGIS ST_ClusterDBSCAN to group stationary GPS points (speed <= 5 mph)
    into spatial clusters with eps=0.005 (~500m radius). Only clusters with at
    least `min_hours` cumulative presence are returned.

    Args:
        conn: psycopg2 connection (not cursor — this is a complex query).
        limit: Maximum number of clusters to return, ordered by visit-day count.
        min_hours: Minimum cumulative hours at a cluster to include it.

    Returns:
        List of tuples, each containing:
            (cluster_id, point_count, centroid_lat, centroid_lon, first_seen,
             last_seen, night_points, years_array, day_count, total_hours,
             night_dates_array)

        - cluster_id: arbitrary integer grouping ID
        - point_count: total GPS readings in this cluster
        - centroid_lat/lon: average position
        - first_seen/last_seen: datetime range
        - night_points: count of points between 23:00-06:00 (overnight indicator)
        - years_array: sorted list of years with visits
        - day_count: number of distinct calendar days visited
        - total_hours: cumulative hours of presence
        - night_dates_array: dates with nighttime points (for overnight detection)
    """
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
        HAVING COALESCE((SELECT SUM(hours_on_day) FROM daily_hours dh WHERE dh.cluster_id = c.cluster_id), 0) >= %s
        ORDER BY day_count DESC
        LIMIT %s
    ''', (min_hours, limit))

    clusters = cur.fetchall()
    cur.close()
    return clusters


def get_daily_location_bounds(conn):
    """
    Get the first and last stationary GPS point for each calendar day.

    This is the foundation for overnight-stay and travel-day detection.
    Only considers stationary points (speed <= 5 mph).

    Args:
        conn: psycopg2 connection.

    Returns:
        List of tuples:
            (day, first_ts, first_lat, first_lon, last_ts, last_lat, last_lon)

        Ordered by day ascending.
    """
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
    cur.close()
    return rows


def get_overnight_stays(conn):
    """
    Identify overnight stays by comparing consecutive days' GPS positions.

    An overnight stay is detected when the last stationary point of day N
    is within 1km of the first stationary point of day N+1, and the days
    are consecutive.

    Args:
        conn: psycopg2 connection.

    Returns:
        List of dicts, each with:
            - date: the night of the stay (date object)
            - lat: average latitude of the overnight position
            - lon: average longitude of the overnight position
    """
    rows = get_daily_location_bounds(conn)

    overnights = []
    for i in range(len(rows) - 1):
        day1, _, _, _, last_ts, last_lat, last_lon = rows[i]
        day2, first_ts, first_lat, first_lon, _, _, _ = rows[i + 1]

        if day2 - day1 != timedelta(days=1):
            continue

        dist = haversine_km(last_lat, last_lon, first_lat, first_lon)

        if dist < 1.0:
            overnights.append({
                'date': day1,
                'lat': (last_lat + first_lat) / 2,
                'lon': (last_lon + first_lon) / 2,
            })

    return overnights


def get_travel_days(conn):
    """
    Identify travel days where the user moved >100km overnight.

    A travel day is day N+1 when the first stationary point of day N+1
    is more than 100km from the last stationary point of day N, and the
    days are consecutive. This typically indicates a flight, long drive,
    or train journey.

    Args:
        conn: psycopg2 connection.

    Returns:
        List of dicts, each with:
            - date: the arrival date (date object)
            - from_lat, from_lon: previous day's last position
            - to_lat, to_lon: this day's first position
            - distance_km: great-circle distance between the two points
    """
    rows = get_daily_location_bounds(conn)

    travel_days = []
    for i in range(len(rows) - 1):
        day1, _, _, _, _, last_lat, last_lon = rows[i]
        day2, _, first_lat, first_lon, _, _, _ = rows[i + 1]

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


# ---------------------------------------------------------------------------
# Flight queries
# ---------------------------------------------------------------------------

def get_all_flights(cur):
    """
    Get all commercial flights, ordered by date descending.

    Returns all flights regardless of source (flightdiary, gps-detected,
    merged). For deduplication-aware queries, filter on source != 'gps-detected'
    if a corresponding 'merged' row exists, but in practice the merge workflow
    already removes redundant gps-detected rows.

    Args:
        cur: psycopg2 cursor.

    Returns:
        List of dicts with keys matching the flights table columns:
            date, flight_number, dep_airport, dep_airport_name, arr_airport,
            arr_airport_name, dep_time, arr_time, duration, airline,
            airline_code, aircraft_type, aircraft_code, registration,
            seat_number, seat_type, flight_class, flight_reason, notes,
            source, dep_lat, dep_lon, arr_lat, arr_lon, distance_km

    Integer columns decode as:
        seat_type: 1=Window, 2=Middle, 3=Aisle
        flight_class: 1=Economy, 2=Business, 3=First, 4=Economy Plus
        flight_reason: 1=Leisure, 2=Business
    """
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


def get_flights_by_source(cur, source):
    """
    Get flights filtered by data source.

    Args:
        cur: psycopg2 cursor.
        source: One of 'flightdiary', 'gps-detected', 'merged'.

    Returns:
        List of tuples (positional, not dicts) with columns:
            id, date, flight_number, dep_airport, arr_airport, dep_time,
            arr_time, duration, airline, airline_code, aircraft_type,
            aircraft_code, registration, seat_number, seat_type,
            flight_class, flight_reason, notes, dep_lat, dep_lon,
            arr_lat, arr_lon, distance_km
    """
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


# ---------------------------------------------------------------------------
# GA (General Aviation) flight queries
# ---------------------------------------------------------------------------

def get_all_ga_flights(cur):
    """
    Get all general aviation logbook entries, ordered by date descending.

    Note: airport codes in ga_flights are ICAO (4-letter, e.g. EGLL),
    not IATA (3-letter, e.g. LHR) as used in the flights table.

    Hour columns represent decimal hours (e.g. 1.50 = 1 hour 30 minutes).
    The category breakdown is:
        - SEP = Single Engine Piston
        - MEP = Multi Engine Piston
        - PIC = Pilot in Command
        - Dual = Dual instruction (with instructor)

    Args:
        cur: psycopg2 cursor.

    Returns:
        List of dicts with keys matching the ga_flights table columns.
    """
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


# ---------------------------------------------------------------------------
# Skiing queries
# ---------------------------------------------------------------------------

def get_all_skiing_days(cur):
    """
    Get all skiing day records, ordered by date descending.

    Each row represents one day at a ski resort with aggregated statistics
    from GPS tracking (SkiTracks app).

    The `season` column follows ski-season convention spanning two calendar
    years (e.g. "2023/2024" for the winter starting in late 2023).

    Args:
        cur: psycopg2 cursor.

    Returns:
        List of dicts with keys:
            date, location, duration_hours, distance_km, vertical_up_m,
            vertical_down_m, max_speed_kmh, avg_speed_kmh, max_altitude_m,
            min_altitude_m, num_runs, num_lifts, platform, season
    """
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


# ---------------------------------------------------------------------------
# Visualization queries
# ---------------------------------------------------------------------------

def get_location_clusters_simple(conn):
    """
    Simplified location cluster query for map visualization.

    Similar to get_location_clusters() but with a lower threshold (2 visit days
    instead of 3 hours) and returns dicts instead of tuples.

    Args:
        conn: psycopg2 connection.

    Returns:
        List of dicts, each with:
            - id: cluster ID
            - points: total GPS readings
            - visits: distinct days visited
            - lat, lon: centroid coordinates
            - first, last: date strings of first/last visit
            - years: list of years with visits
    """
    cur = conn.cursor()
    cur.execute("""
        WITH stationary AS (
            SELECT
                geom::geometry as geom,
                ts::date as visit_date,
                EXTRACT(YEAR FROM ts) as year
            FROM gps_points
            WHERE speed_mph IS NULL OR speed_mph <= 5
        ),
        clustered AS (
            SELECT
                ST_ClusterDBSCAN(geom, eps := 0.005, minpoints := 3) OVER() as cluster_id,
                geom,
                visit_date,
                year
            FROM stationary
        )
        SELECT
            cluster_id,
            COUNT(*) as total_points,
            COUNT(DISTINCT visit_date) as visit_days,
            AVG(ST_Y(geom)) as lat,
            AVG(ST_X(geom)) as lon,
            MIN(visit_date) as first_visit,
            MAX(visit_date) as last_visit,
            array_agg(DISTINCT year ORDER BY year) as years
        FROM clustered
        WHERE cluster_id IS NOT NULL
        GROUP BY cluster_id
        HAVING COUNT(DISTINCT visit_date) >= 2
        ORDER BY visit_days DESC
    """)

    clusters = []
    for row in cur.fetchall():
        clusters.append({
            'id': int(row[0]) if row[0] else 0,
            'points': int(row[1]),
            'visits': int(row[2]),
            'lat': float(row[3]),
            'lon': float(row[4]),
            'first': str(row[5]),
            'last': str(row[6]),
            'years': [int(y) for y in row[7]] if row[7] else []
        })

    cur.close()
    return clusters


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    """
    Calculate great-circle distance between two points in kilometres.

    Uses the Haversine formula. Coordinates are in decimal degrees (WGS84).

    Args:
        lat1, lon1: First point coordinates.
        lat2, lon2: Second point coordinates.

    Returns:
        Distance in kilometres (float).
    """
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))
