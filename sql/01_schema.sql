-- =============================================================================
-- 01_schema.sql – Star schema for the German electricity market (SMARD, DE-LU)
--
-- Grain
--   fact_hourly      one row per UTC hour and generation source
--   fact_price_load  one row per UTC hour (price and load have no source)
--
-- Keys
--   timestamp_key  BIGINT yyyymmddhh of the hour start in **UTC** (unique, also on DST days)
--   date_key       INT    yyyymmdd of the **local** (Europe/Berlin) date
--   hour_key       SMALLINT 0–23, **local** hour of day
--   Local date/hour drive all reporting; UTC keeps every hour unique (the
--   repeated 02:00 hour on the last Sunday in October is two different UTC hours).
--
-- Idempotent: CREATE ... IF NOT EXISTS, and static dimensions are upserted.
-- =============================================================================

-- ----------------------------------------------------------------------------
-- Dimensions
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_date (
    date_key            INTEGER      PRIMARY KEY,          -- yyyymmdd
    date                DATE         NOT NULL UNIQUE,
    year                SMALLINT     NOT NULL,
    quarter             SMALLINT     NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month               SMALLINT     NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name          VARCHAR(9)   NOT NULL,
    year_month          CHAR(7)      NOT NULL,             -- 'YYYY-MM', handy for axes
    week                SMALLINT     NOT NULL,             -- ISO week
    weekday             SMALLINT     NOT NULL CHECK (weekday BETWEEN 1 AND 7),  -- ISO: 1 = Monday
    weekday_name        VARCHAR(9)   NOT NULL,
    is_weekend          BOOLEAN      NOT NULL,
    season              VARCHAR(6)   NOT NULL,             -- meteorological: Winter = Dec–Feb
    is_public_holiday   BOOLEAN      NOT NULL,             -- German nationwide holidays only
    holiday_name        VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS dim_hour (
    hour_key            SMALLINT     PRIMARY KEY CHECK (hour_key BETWEEN 0 AND 23),
    hour_label          CHAR(5)      NOT NULL,             -- '08:00'
    -- Peak window 08:00–20:00 (hours 8..19). Whether an hour is actually *peak*
    -- also depends on the weekday -> see dim_datetime.is_peak.
    is_peak_window      BOOLEAN      NOT NULL,
    day_period          VARCHAR(9)   NOT NULL              -- Night / Morning / Midday / Evening
);

CREATE TABLE IF NOT EXISTS dim_source (
    source_key              SMALLINT     PRIMARY KEY,
    source_name             VARCHAR(30)  NOT NULL UNIQUE,  -- technical name used by the pipeline
    source_label            VARCHAR(40)  NOT NULL,         -- display name for reports
    category                VARCHAR(10)  NOT NULL
        CHECK (category IN ('renewable', 'fossil', 'nuclear', 'other')),
    is_variable_renewable   BOOLEAN      NOT NULL,         -- weather-dependent: wind + solar
    smard_filter_id         INTEGER      NOT NULL UNIQUE   -- lineage back to the SMARD series
);

-- One row per UTC hour: the shared hourly axis for both fact tables.
CREATE TABLE IF NOT EXISTS dim_datetime (
    timestamp_key       BIGINT       PRIMARY KEY,          -- yyyymmddhh (UTC)
    timestamp_utc       TIMESTAMPTZ  NOT NULL UNIQUE,
    timestamp_local     TIMESTAMP    NOT NULL,             -- Europe/Berlin wall clock (not unique on DST day!)
    utc_offset_h        SMALLINT     NOT NULL CHECK (utc_offset_h IN (1, 2)),  -- 1 = CET, 2 = CEST
    date_key            INTEGER      NOT NULL REFERENCES dim_date (date_key),
    hour_key            SMALLINT     NOT NULL REFERENCES dim_hour (hour_key),
    is_peak             BOOLEAN      NOT NULL              -- Mon–Fri 08:00–20:00 local (EEX definition)
);

-- ----------------------------------------------------------------------------
-- Facts
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_hourly (
    timestamp_key       BIGINT        NOT NULL REFERENCES dim_datetime (timestamp_key),
    date_key            INTEGER       NOT NULL REFERENCES dim_date (date_key),
    hour_key            SMALLINT      NOT NULL REFERENCES dim_hour (hour_key),
    source_key          SMALLINT      NOT NULL REFERENCES dim_source (source_key),
    generation_mwh      NUMERIC(12,3) NOT NULL CHECK (generation_mwh >= 0),
    PRIMARY KEY (timestamp_key, source_key)
);

CREATE TABLE IF NOT EXISTS fact_price_load (
    timestamp_key       BIGINT        PRIMARY KEY REFERENCES dim_datetime (timestamp_key),
    date_key            INTEGER       NOT NULL REFERENCES dim_date (date_key),
    hour_key            SMALLINT      NOT NULL REFERENCES dim_hour (hour_key),
    -- 4 decimals: since 2025-10-01 the hourly price is a mean of four 2-decimal quarter-hour prices.
    price_eur_mwh       NUMERIC(10,4),
    consumption_mwh     NUMERIC(12,3) CHECK (consumption_mwh >= 0)
);

-- Indexes for the typical filters/joins (PK columns are indexed already).
CREATE INDEX IF NOT EXISTS ix_fact_hourly_date     ON fact_hourly (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_hourly_source   ON fact_hourly (source_key, date_key);
CREATE INDEX IF NOT EXISTS ix_fact_price_load_date ON fact_price_load (date_key);
CREATE INDEX IF NOT EXISTS ix_dim_datetime_date    ON dim_datetime (date_key);

-- ----------------------------------------------------------------------------
-- Static dimension content (upserts keep this idempotent)
-- ----------------------------------------------------------------------------
INSERT INTO dim_hour (hour_key, hour_label, is_peak_window, day_period)
SELECT h,
       to_char(make_time(h, 0, 0), 'HH24:MI'),
       h BETWEEN 8 AND 19,
       CASE WHEN h < 6 THEN 'Night' WHEN h < 11 THEN 'Morning'
            WHEN h < 16 THEN 'Midday' WHEN h < 22 THEN 'Evening' ELSE 'Night' END
FROM generate_series(0, 23) AS h
ON CONFLICT (hour_key) DO UPDATE
SET hour_label = EXCLUDED.hour_label,
    is_peak_window = EXCLUDED.is_peak_window,
    day_period = EXCLUDED.day_period;

-- Fixed surrogate keys (not SERIAL) so keys never change between runs.
-- Pumped storage is a storage technology, not primary generation -> 'other'.
-- "Other conventional" (oil, mine gas, non-biogenic waste, ...) -> 'fossil'.
INSERT INTO dim_source (source_key, source_name, source_label, category, is_variable_renewable, smard_filter_id)
VALUES
    ( 1, 'wind_onshore',       'Wind onshore',        'renewable', TRUE,  4067),
    ( 2, 'wind_offshore',      'Wind offshore',       'renewable', TRUE,  1225),
    ( 3, 'solar',              'Solar (PV)',          'renewable', TRUE,  4068),
    ( 4, 'biomass',            'Biomass',             'renewable', FALSE, 4066),
    ( 5, 'hydro',              'Hydro',               'renewable', FALSE, 1226),
    ( 6, 'other_renewable',    'Other renewables',    'renewable', FALSE, 1228),
    ( 7, 'lignite',            'Lignite',             'fossil',    FALSE, 1223),
    ( 8, 'hard_coal',          'Hard coal',           'fossil',    FALSE, 4069),
    ( 9, 'natural_gas',        'Natural gas',         'fossil',    FALSE, 4071),
    (10, 'other_conventional', 'Other conventional',  'fossil',    FALSE, 1227),
    (11, 'nuclear',            'Nuclear',             'nuclear',   FALSE, 1224),
    (12, 'pumped_storage',     'Pumped storage',      'other',     FALSE, 4070)
ON CONFLICT (source_key) DO UPDATE
SET source_name = EXCLUDED.source_name,
    source_label = EXCLUDED.source_label,
    category = EXCLUDED.category,
    is_variable_renewable = EXCLUDED.is_variable_renewable,
    smard_filter_id = EXCLUDED.smard_filter_id;
