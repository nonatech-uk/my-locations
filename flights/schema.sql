-- Flights table schema for mylocation system
-- Run: psql -h 10.8.0.8 -U mylocation -d mylocation -f schema.sql

-- Backup first (if not already done):
-- CREATE TABLE gps_points_backup_$(date +%Y%m%d) AS SELECT * FROM gps_points;

CREATE TABLE IF NOT EXISTS flights (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    flight_number TEXT,

    -- Route
    dep_airport TEXT NOT NULL,        -- IATA code (LHR)
    dep_airport_name TEXT,            -- Full name
    dep_icao TEXT,                    -- ICAO code (EGLL)
    arr_airport TEXT NOT NULL,
    arr_airport_name TEXT,
    arr_icao TEXT,

    -- Times
    dep_time TIME,
    arr_time TIME,
    duration INTERVAL,

    -- Flight details
    airline TEXT,
    airline_code TEXT,                -- BA, LX, etc.
    aircraft_type TEXT,               -- Boeing 777-200
    aircraft_code TEXT,               -- B772
    registration TEXT,                -- G-VIIE

    -- Passenger details
    seat_number TEXT,
    seat_type INTEGER,                -- 1=window, 2=middle, 3=aisle
    flight_class INTEGER,             -- 1=economy, 2=business, etc.
    flight_reason INTEGER,            -- 1=leisure, 2=business

    -- Metadata
    notes TEXT,
    source TEXT,                      -- 'flightdiary', 'gps-detected', 'merged'
    gps_matched BOOLEAN DEFAULT FALSE,

    -- Coordinates for mapping
    dep_lat DOUBLE PRECISION,
    dep_lon DOUBLE PRECISION,
    arr_lat DOUBLE PRECISION,
    arr_lon DOUBLE PRECISION,
    distance_km INTEGER,

    UNIQUE(date, dep_airport, arr_airport, flight_number)
);

CREATE INDEX IF NOT EXISTS idx_flights_date ON flights(date);
CREATE INDEX IF NOT EXISTS idx_flights_route ON flights(dep_airport, arr_airport);
CREATE INDEX IF NOT EXISTS idx_flights_source ON flights(source);

-- Show table info after creation
\d flights
