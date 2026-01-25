# GA Flying Logbook Module

Import and analyse General Aviation flying logbook data from Excel.

## Overview

This module imports pilot flight records from an Excel logbook, stores them in PostgreSQL, and generates HTML/Markdown reports.

**Data source:** `data/ga/Stu LogBook.xlsx` - "Log Book" sheet
**Database table:** `ga_flights`
**Reports:** `reports/ga_report.html`, `reports/ga_report.md`

## Current Stats (as of import)

- **592 flights** from 1997-08-13 to 2021-05-29
- **639.8 total hours**
- **49 unique aircraft**, **17 aircraft types**, **57 airports**

## Files

| File | Purpose |
|------|---------|
| `schema.sql` | PostgreSQL table definition |
| `ga_import.py` | Excel parser and database importer |
| `ga_report.py` | Report generator (HTML + Markdown) |

## Database Schema

```sql
CREATE TABLE ga_flights (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    aircraft_type TEXT,           -- C152, PA28, PA34, etc.
    registration TEXT,            -- G-LSMI
    captain TEXT,                 -- PIC name (instructor for training flights)
    operating_capacity TEXT,      -- PUT, P1, P2, etc.
    dep_airport TEXT,             -- ICAO code
    arr_airport TEXT,             -- ICAO code
    dep_time TIME,
    arr_time TIME,

    -- Hour categories
    hours_sep_pic NUMERIC(5,2),        -- Single Engine PIC
    hours_sep_dual NUMERIC(5,2),       -- Single Engine Dual
    hours_mep_pic NUMERIC(5,2),        -- Multi Engine PIC
    hours_mep_dual NUMERIC(5,2),       -- Multi Engine Dual
    hours_pic_3 NUMERIC(5,2),          -- Additional category 3
    hours_dual_3 NUMERIC(5,2),
    hours_pic_4 NUMERIC(5,2),          -- Additional category 4
    hours_dual_4 NUMERIC(5,2),

    -- Special hour types
    hours_instrument NUMERIC(5,2),     -- Instrument flying
    hours_as_instructor NUMERIC(5,2),  -- Hours giving instruction
    hours_simulator NUMERIC(5,2),      -- Simulator hours
    hours_total NUMERIC(5,2),          -- Total flight time

    instructor TEXT,                   -- Instructor name
    exercise TEXT,                     -- Training exercise refs / comments

    UNIQUE(date, registration, dep_airport, arr_airport, dep_time)
);
```

## Key Data Fields

### Operating Capacity
- `PUT` - Pilot Under Training (student)
- `P1` - Pilot in Command
- `P2` - Co-Pilot

### Hour Categories
- **SEP** - Single Engine Piston (C152, PA28, etc.)
- **MEP** - Multi Engine Piston (PA34, BE76, PA23)
- **PIC** - Pilot in Command hours
- **Dual** - Training hours with instructor

### Aircraft Types Flown
Top types by hours: PA28 (279h), PA34 (132h), PA28-235 (50h), DHC-1 (37h), BE76 (28h)

## Usage

```bash
# Import from Excel (with dry-run first)
python ga/ga_import.py --dry-run
python ga/ga_import.py

# Generate reports
python ga/ga_report.py

# Generate specific format only
python ga/ga_report.py --html
python ga/ga_report.py --md
```

## Report Statistics Available

The `calculate_statistics()` function in `ga_report.py` computes:

- **Totals:** flights, hours (total, PIC, dual, instrument, as instructor)
- **By Year:** flight count and hours per year
- **By Aircraft Type:** flights and hours per type (C152, PA28, etc.)
- **By Registration:** flights and hours per individual aircraft
- **By Instructor:** training flights and dual hours per instructor
- **By Capacity:** flight count per operating capacity
- **Airports:** visit counts per ICAO code
- **Routes:** frequency of each origin-destination pair
- **Records:** longest flight, most flights in a day

## Airport Name Lookup

The report uses OpenFlights database to resolve ICAO codes to airport names:
- URL: `https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat`
- Cached in memory during report generation
- "Airport" and "Aerodrome" suffixes are stripped from names

## Excel Column Mapping

| Col | Field | Notes |
|-----|-------|-------|
| A (1) | Date | Excel datetime |
| E (5) | Aircraft Type | C152, PA28, etc. |
| F (6) | Registration | Without G- prefix in source |
| G (7) | Captain | Instructor name for training flights |
| H (8) | Operating Capacity | PUT, P1, P2 |
| I (9) | Departure Airport | ICAO code |
| J (10) | Arrival Airport | ICAO code |
| K (11) | Departure Time | |
| L (12) | Arrival Time | |
| M-N (13-14) | SEP In Command / Dual | |
| O-P (15-16) | MEP In Command / Dual | |
| Q-R (17-18) | Category 3 In Command / Dual | |
| S-T (19-20) | Category 4 In Command / Dual | |
| U (21) | Instrument Flying | Decimal hours |
| V (22) | As Instructor | Hours giving instruction |
| W (23) | Simulator | Simulator hours |
| X (24) | Flight Time | Total hours |
| Y (25) | Comments | Exercise references |

## Future: Web Dashboard

Planned features for web visualisation:

### Dashboard Views
- **Summary cards:** Total hours, flights, airports, aircraft
- **Timeline:** Flights over time, hours by year/month
- **Map:** Airports visited, routes flown (using Leaflet.js)
- **Aircraft log:** Hours per registration, per type
- **Training progress:** Dual vs PIC hours over time, by instructor
- **Currency:** Recent flights, time since last flight per type

### Potential API Endpoints
```
GET /api/ga/stats              - Summary statistics
GET /api/ga/flights            - Flight list (paginated)
GET /api/ga/flights/:id        - Single flight details
GET /api/ga/by-year            - Yearly breakdown
GET /api/ga/by-aircraft        - Aircraft breakdown
GET /api/ga/by-airport         - Airport statistics
GET /api/ga/airports           - List of airports with coordinates
GET /api/ga/routes             - Route frequency data
```

### Integration Points
- Combine with commercial flights from `flights` table
- Show on same map as GPS tracks
- Cross-reference airports between GA and commercial flying

### Tech Stack Considerations
- Backend: Python Flask/FastAPI (matches existing codebase)
- Frontend: Simple HTML/JS or React
- Maps: Leaflet.js (already used in `visualize.py`)
- Charts: Chart.js or similar

## Dependencies

- `openpyxl` - Excel file parsing
- `psycopg2-binary` - PostgreSQL connection
- `requests` - Airport database download
