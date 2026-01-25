-- GA Flying Logbook table schema
-- Run: psql -h 10.8.0.8 -U mylocation -d mylocation -f schema.sql

CREATE TABLE IF NOT EXISTS ga_flights (
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
    -- Single Engine Piston (SEP)
    hours_sep_pic NUMERIC(5,2),   -- In Command (Single Engine)
    hours_sep_dual NUMERIC(5,2),  -- Dual (Single Engine)
    -- Multi Engine Piston (MEP)
    hours_mep_pic NUMERIC(5,2),   -- In Command (Multi Engine)
    hours_mep_dual NUMERIC(5,2),  -- Dual (Multi Engine)
    -- Additional categories (cols 17-20)
    hours_pic_3 NUMERIC(5,2),     -- In Command (category 3)
    hours_dual_3 NUMERIC(5,2),    -- Dual (category 3)
    hours_pic_4 NUMERIC(5,2),     -- In Command (category 4)
    hours_dual_4 NUMERIC(5,2),    -- Dual (category 4)

    -- Special hour types
    hours_instrument NUMERIC(5,2),     -- Instrument flying hours
    hours_as_instructor NUMERIC(5,2),  -- Hours giving instruction
    hours_simulator NUMERIC(5,2),      -- Simulator hours
    hours_total NUMERIC(5,2),          -- Total flight time

    instructor TEXT,              -- Instructor name (same as captain for training)
    exercise TEXT,                -- Training exercise refs / comments
    comments TEXT,

    UNIQUE(date, registration, dep_airport, arr_airport, dep_time)
);

CREATE INDEX IF NOT EXISTS idx_ga_flights_date ON ga_flights(date);
CREATE INDEX IF NOT EXISTS idx_ga_flights_aircraft ON ga_flights(registration);
CREATE INDEX IF NOT EXISTS idx_ga_flights_type ON ga_flights(aircraft_type);

-- Show table info after creation
\d ga_flights
