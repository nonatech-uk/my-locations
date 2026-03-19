-- Skiing days: one row per day of skiing, with aggregated statistics.
--
-- Data is imported from SkiTracks GPS app exports. Each row summarises a full
-- day at a ski resort — distance, vertical, speed, run/lift counts.
--
-- The location column is populated by resort_matcher.py, which compares the
-- day's GPS points against a known list of ski resorts (Haversine match within
-- 30km). May be NULL for unmatched days.
--
-- The season column follows ski-season convention spanning two calendar years
-- (e.g. "2023/2024" for the winter starting in late 2023).
--
-- Invariant: one row per date (date is UNIQUE). Append-only in practice.
--
-- Run: psql -h <host> -U mylocation -d mylocation -f schema.sql

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
