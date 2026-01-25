-- Skiing days table schema for mylocation system
-- Run: psql -h 10.8.0.8 -U mylocation -d mylocation -f schema.sql

CREATE TABLE IF NOT EXISTS skiing_days (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    location TEXT,
    duration_hours NUMERIC,
    distance_km NUMERIC,
    vertical_up_m INTEGER,
    vertical_down_m INTEGER,
    max_speed_kmh NUMERIC,
    avg_speed_kmh NUMERIC,
    max_altitude_m INTEGER,
    min_altitude_m INTEGER,
    num_runs INTEGER,
    num_lifts INTEGER,
    platform TEXT,                    -- Device used (iPhone, Apple Watch)
    season TEXT,                      -- e.g., "2023/2024"
    track_id TEXT                     -- Reference to TrackXXXXX folder
);

CREATE INDEX IF NOT EXISTS idx_skiing_days_date ON skiing_days(date);
CREATE INDEX IF NOT EXISTS idx_skiing_days_season ON skiing_days(season);
CREATE INDEX IF NOT EXISTS idx_skiing_days_location ON skiing_days(location);

-- Show table info after creation
\d skiing_days
