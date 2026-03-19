# Data Model Reference

This document describes the database schema for the my-locations personal
location tracking system. It is intended as a guide for external read-only
consumers (such as an MCP server) that need to understand and query this data.

## Overview

The system aggregates personal location and travel data from multiple sources
into a PostgreSQL + PostGIS database. There are four main tables:

| Table | What it stores | Row count character | Primary key |
|-------|---------------|---------------------|-------------|
| `gps_points` | Raw GPS readings from phone tracking apps | Tens/hundreds of thousands | `id` (serial) |
| `flights` | Commercial airline flights (passenger) | Hundreds | `id` (serial) |
| `ga_flights` | General aviation logbook entries (pilot) | Hundreds | `id` (serial) |
| `skiing_days` | One row per day of skiing, with stats | Tens to low hundreds | `id` (serial) |

All tables are append-oriented. `gps_points` is effectively append-only
(inserts use `ON CONFLICT DO NOTHING`). The `flights` table has a merge
workflow that can update `source` and delete duplicates, but does not
modify historical flight details.

---

## Tables for Read-Only Consumers

### Which tables to query

For **reporting and analysis**, query all four tables freely — they all
contain human-meaningful data.

For **location history questions** ("where was I on date X?", "how many
countries have I visited?"), the derived analysis is computed at query time
from `gps_points` using PostGIS spatial clustering. There are no
pre-computed summary tables. See [Canonical Query Patterns](#canonical-query-patterns)
below.

### What to avoid

- Do not write to any table.
- Do not rely on `gps_points.id` ordering — timestamps (`ts`) are the
  canonical ordering.
- The `flights.source` column has internal workflow meaning (`flightdiary`,
  `gps-detected`, `merged`). For reporting, treat all rows equally regardless
  of source. If deduplication matters, prefer rows where `source = 'merged'`
  or `source = 'flightdiary'` over `source = 'gps-detected'`, since merged
  records combine the best of both.

---

## Table Details

### `gps_points`

Raw GPS readings from multiple tracking apps. This is the largest table and
the foundation for all location analysis.

| Column | Type | Human-meaningful? | Description |
|--------|------|-------------------|-------------|
| `id` | SERIAL PK | No | Internal row ID |
| `device_id` | VARCHAR | Semi | Source identifier: `followmee`, `Placeme`, `skitracks` |
| `device_name` | VARCHAR | Yes | Display name of the device/source |
| `ts` | TIMESTAMP | Yes | UTC timestamp of the reading |
| `lat` | DOUBLE | Yes | Latitude (WGS84) |
| `lon` | DOUBLE | Yes | Longitude (WGS84) |
| `altitude_m` | DOUBLE | Yes | Altitude in metres |
| `altitude_ft` | DOUBLE | Yes | Altitude in feet (redundant with altitude_m) |
| `speed_mph` | DOUBLE | Yes | Speed in miles per hour (NULL when stationary) |
| `speed_kmh` | DOUBLE | Yes | Speed in km/h (redundant with speed_mph) |
| `direction` | INTEGER | Yes | Compass heading in degrees |
| `accuracy_m` | DOUBLE | Semi | GPS horizontal accuracy in metres |
| `battery_pct` | DOUBLE | No | Device battery level at reading time |
| `source_type` | VARCHAR | Semi | Import method: `followmee-api`, `kml`, `placeme`, `skitracks` |
| `geom` | GEOMETRY | No | PostGIS point (SRID 4326), derived from lat/lon |

**Invariants:**
- Append-only — rows are never updated or deleted.
- Deduplicated on `(device_id, ts)` — one reading per device per timestamp.
- `geom` is always `ST_SetSRID(ST_MakePoint(lon, lat), 4326)`.
- Stationary points have `speed_mph IS NULL OR speed_mph <= 5`. This
  threshold is used throughout all location analysis.

**Data sources:**
- FollowMee phone tracker (API sync and KML export)
- Placeme location history (HTML export)
- SkiTracks GPS recordings (imported during skiing analysis)

---

### `flights`

Commercial airline flights as a passenger. Combines data from a flight diary
service and GPS-detected journeys.

| Column | Type | Human-meaningful? | Description |
|--------|------|-------------------|-------------|
| `id` | SERIAL PK | No | Internal row ID |
| `date` | DATE | Yes | Flight date |
| `flight_number` | TEXT | Yes | e.g. `BA123` |
| `dep_airport` | TEXT | Yes | IATA departure code (e.g. `LHR`) |
| `dep_airport_name` | TEXT | Yes | Full airport name |
| `dep_icao` | TEXT | Semi | ICAO code (e.g. `EGLL`) |
| `arr_airport` | TEXT | Yes | IATA arrival code |
| `arr_airport_name` | TEXT | Yes | Full airport name |
| `arr_icao` | TEXT | Semi | ICAO code |
| `dep_time` | TIME | Yes | Departure time |
| `arr_time` | TIME | Yes | Arrival time |
| `duration` | INTERVAL | Yes | Flight duration |
| `airline` | TEXT | Yes | Airline name |
| `airline_code` | TEXT | Yes | 2-letter airline code (e.g. `BA`) |
| `aircraft_type` | TEXT | Yes | e.g. `Boeing 777-200` |
| `aircraft_code` | TEXT | Semi | e.g. `B772` |
| `registration` | TEXT | Yes | Aircraft tail number (e.g. `G-VIIE`) |
| `seat_number` | TEXT | Yes | e.g. `14A` |
| `seat_type` | INTEGER | Yes | 1=window, 2=middle, 3=aisle |
| `flight_class` | INTEGER | Yes | 1=economy, 2=business, 3=first, 4=economy plus |
| `flight_reason` | INTEGER | Yes | 1=leisure, 2=business |
| `notes` | TEXT | Yes | Free-text notes |
| `source` | TEXT | Internal | `flightdiary`, `gps-detected`, or `merged` |
| `gps_matched` | BOOLEAN | Internal | Whether GPS data corroborates this flight |
| `dep_lat` | DOUBLE | Semi | Departure airport latitude |
| `dep_lon` | DOUBLE | Semi | Departure airport longitude |
| `arr_lat` | DOUBLE | Semi | Arrival airport latitude |
| `arr_lon` | DOUBLE | Semi | Arrival airport longitude |
| `distance_km` | INTEGER | Yes | Great-circle distance |

**Invariants:**
- Deduplicated on `(date, dep_airport, arr_airport, flight_number)`.
- The `source` column tracks provenance: `flightdiary` = imported from
  MyFlightDiary.com, `gps-detected` = inferred from GPS data,
  `merged` = both sources matched and combined.
- GPS-detected records may lack flight number, airline, seat, and class info.
- Merged records keep all diary details and set `gps_matched = TRUE`.

**Integer code mappings:**
- `seat_type`: 1=Window, 2=Middle, 3=Aisle
- `flight_class`: 1=Economy, 2=Business, 3=First, 4=Economy Plus
- `flight_reason`: 1=Leisure, 2=Business

---

### `ga_flights`

General aviation (light aircraft) logbook entries. The owner is a pilot;
these record flights where they were crew, not a passenger.

| Column | Type | Human-meaningful? | Description |
|--------|------|-------------------|-------------|
| `id` | SERIAL PK | No | Internal row ID |
| `date` | DATE | Yes | Flight date |
| `aircraft_type` | TEXT | Yes | Type designator: `C152`, `PA28`, `PA34`, etc. |
| `registration` | TEXT | Yes | Tail number (e.g. `G-LSMI`) |
| `captain` | TEXT | Yes | Pilot in command name |
| `operating_capacity` | TEXT | Yes | Role: `PUT` (under training), `P1` (PIC), `P2` (co-pilot) |
| `dep_airport` | TEXT | Yes | ICAO departure code |
| `arr_airport` | TEXT | Yes | ICAO arrival code |
| `dep_time` | TIME | Yes | Departure time |
| `arr_time` | TIME | Yes | Arrival time |
| `hours_sep_pic` | NUMERIC(5,2) | Yes | Single Engine Piston — Pilot in Command hours |
| `hours_sep_dual` | NUMERIC(5,2) | Yes | Single Engine Piston — Dual (training) hours |
| `hours_mep_pic` | NUMERIC(5,2) | Yes | Multi Engine Piston — PIC hours |
| `hours_mep_dual` | NUMERIC(5,2) | Yes | Multi Engine Piston — Dual hours |
| `hours_pic_3` | NUMERIC(5,2) | Semi | Additional PIC category (column 17 in logbook) |
| `hours_dual_3` | NUMERIC(5,2) | Semi | Additional dual category (column 18) |
| `hours_pic_4` | NUMERIC(5,2) | Semi | Additional PIC category (column 19) |
| `hours_dual_4` | NUMERIC(5,2) | Semi | Additional dual category (column 20) |
| `hours_instrument` | NUMERIC(5,2) | Yes | Instrument flying hours |
| `hours_as_instructor` | NUMERIC(5,2) | Yes | Hours spent giving instruction |
| `hours_simulator` | NUMERIC(5,2) | Yes | Simulator hours (not actual flight time) |
| `hours_total` | NUMERIC(5,2) | Yes | Total flight time for this entry |
| `instructor` | TEXT | Yes | Instructor name (for training flights) |
| `exercise` | TEXT | Yes | Training exercise references/comments |
| `comments` | TEXT | Yes | Free-text notes |

**Invariants:**
- Deduplicated on `(date, registration, dep_airport, arr_airport, dep_time)`.
- Airport codes are ICAO (4-letter), not IATA, unlike the `flights` table.
- `hours_total` is the authoritative total; the category breakdowns
  (SEP/MEP/PIC/Dual) should sum to `hours_total` but may not perfectly
  due to rounding.
- `hours_pic_3`, `hours_dual_3`, `hours_pic_4`, `hours_dual_4` correspond
  to additional logbook columns that may be unused for most entries.

**Key concepts for querying:**
- Total PIC hours = `hours_sep_pic + hours_mep_pic`
- Total dual (training) hours = `hours_sep_dual + hours_mep_dual`
- Training flights have `instructor IS NOT NULL` and dual hours > 0.
- `captain` is the instructor's name on training flights, `'Self'` on solo.

---

### `skiing_days`

One row per day of skiing, with aggregated statistics from SkiTracks GPS app.

| Column | Type | Human-meaningful? | Description |
|--------|------|-------------------|-------------|
| `id` | SERIAL PK | No | Internal row ID |
| `date` | DATE | Yes | Ski day date (unique) |
| `location` | TEXT | Yes | Ski resort name (matched by GPS or manual) |
| `duration_hours` | NUMERIC | Yes | Time on mountain |
| `distance_km` | NUMERIC | Yes | Total distance covered |
| `vertical_up_m` | INTEGER | Yes | Total elevation gain (metres) |
| `vertical_down_m` | INTEGER | Yes | Total elevation loss (metres) |
| `max_speed_kmh` | NUMERIC | Yes | Peak speed recorded |
| `avg_speed_kmh` | NUMERIC | Yes | Average speed |
| `max_altitude_m` | INTEGER | Yes | Highest point reached |
| `min_altitude_m` | INTEGER | Yes | Lowest point reached |
| `num_runs` | INTEGER | Yes | Number of ski runs completed |
| `num_lifts` | INTEGER | Yes | Number of lift rides taken |
| `platform` | TEXT | Semi | Recording device: `iPhone`, `Apple Watch` |
| `season` | TEXT | Yes | Season string, e.g. `2023/2024` |
| `track_id` | TEXT | No | Reference to SkiTracks export folder |

**Invariants:**
- One row per date (`date` is UNIQUE).
- `location` may be NULL for unmatched days; resort matching is done by
  comparing GPS points to a known list of ski resorts.
- `season` follows the ski-season convention spanning two calendar years.

---

## Canonical Query Patterns

### Location clusters (where have I spent time?)

The system identifies places by spatially clustering stationary GPS points
(speed <= 5 mph) using PostGIS `ST_ClusterDBSCAN(geom, eps := 0.005, minpoints := 3)`.
The `eps` of 0.005 degrees groups points within roughly 500m.

Clusters are filtered to those with at least 3 cumulative hours of presence.
Each cluster yields a centroid lat/lon, count of distinct visit days, date
range, and night-time visit detection.

See `queries.py:get_location_clusters()` for the canonical implementation.

### Overnight stays

Determined by comparing the last GPS point of day N with the first point of
day N+1. If consecutive days and distance < 1km, the person stayed overnight
at that location. This is a Python post-processing step over SQL daily bounds.

See `queries.py:get_overnight_stays()`.

### Travel days

Days where the first GPS point is > 100km from the previous day's last point.
Same daily-bounds query as overnight stays, different distance threshold.

See `queries.py:get_travel_days()`.

### Flight statistics

Query `flights` directly — all rows, all sources. Statistics (by year,
airline, aircraft, route, airport) are computed in Python by iterating
the result set. No SQL aggregation beyond `ORDER BY date`.

See `queries.py:get_all_flights()`.

### GA logbook statistics

Query `ga_flights` directly. Hour breakdowns by category, aircraft type,
instructor, and operating capacity are computed in Python.

See `queries.py:get_all_ga_flights()`.

### Skiing statistics

Query `skiing_days WHERE date IS NOT NULL`. Season and location breakdowns,
personal records, and aggregated totals are computed in Python.

See `queries.py:get_all_skiing_days()`.

---

## Relationships Between Tables

There are **no foreign keys** between tables. The tables are loosely related
by date and geography:

- `gps_points` and `flights`: GPS data can corroborate flight records. The
  `airport_matcher.py` script detects flights from GPS speed/distance
  patterns and matches start/end points to airports. Matched flights have
  `flights.gps_matched = TRUE`.

- `gps_points` and `skiing_days`: Ski track GPS points (with
  `source_type = 'skitracks'`) are the raw data behind `skiing_days`
  summaries. The `resort_matcher.py` script uses these points to determine
  which resort was visited.

- `flights` and `ga_flights`: Both record flights but are completely
  separate — `flights` is commercial passenger travel, `ga_flights` is
  the pilot's logbook for light aircraft.

---

## Database Engine Details

- **PostgreSQL** with **PostGIS** extension (for `geometry` type and spatial functions).
- No ORM — all access is via raw SQL through `psycopg2`.
- No views, stored procedures, triggers, or functions in the database.
- No migrations framework — schemas are in `*/schema.sql` files applied manually.
- Connection details are in environment variables (see `config.py`).

---

## Data Volume and Date Range

The data spans multiple years of personal location tracking. Typical volumes:

- `gps_points`: ~100,000+ rows, dating from ~2013 onwards
- `flights`: ~200-500 rows, dating from ~2005 onwards
- `ga_flights`: ~100-300 rows
- `skiing_days`: ~50-150 rows

All timestamps in `gps_points` are UTC. Date columns in other tables are
date-only (no timezone).
