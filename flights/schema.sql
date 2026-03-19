-- Flights table: commercial airline flights as a passenger.
--
-- Each row is one flight segment. Data comes from two sources:
--   - MyFlightDiary.com CSV exports (source='flightdiary') — has flight number,
--     airline, seat, class info
--   - GPS-detected journeys (source='gps-detected') — inferred from GPS speed
--     and distance, matched to airports within 10km
--   - Merged records (source='merged') — diary + GPS matched by same airports
--     and date (+/- 1 day); keeps diary details, deletes GPS duplicate
--
-- Integer code columns:
--   seat_type:     1=window, 2=middle, 3=aisle
--   flight_class:  1=economy, 2=business, 3=first, 4=economy plus
--   flight_reason: 1=leisure, 2=business
--
-- Airport codes are IATA (3-letter). Coordinates are for the airports, not
-- the aircraft position.
--
-- Invariant: rows are deduplicated on (date, dep_airport, arr_airport, flight_number).
-- The merge workflow may UPDATE source and DELETE gps-detected duplicates,
-- but never modifies historical flight details.
--
-- Run: psql -h <host> -U mylocation -d mylocation -f schema.sql

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
