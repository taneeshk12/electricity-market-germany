-- =============================================================================
-- 02_dim_date.sql – Calendar dimension incl. German nationwide public holidays
--
-- Usage:  CALL fill_dim_date('2023-01-01', '2025-12-31');
-- Idempotent: rows are upserted by date_key.
--
-- Holidays: only the 9 holidays observed in *all* German states. Regional ones
-- (e.g. Corpus Christi, Epiphany) are excluded because the data is national.
-- The pipeline cross-checks this list against the Python `holidays` package.
-- =============================================================================

-- Easter Sunday (Gregorian calendar), anonymous Gregorian / Meeus–Jones–Butcher algorithm.
CREATE OR REPLACE FUNCTION easter_sunday(y INTEGER) RETURNS DATE
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    a INT := y % 19;
    b INT := y / 100;
    c INT := y % 100;
    d INT := b / 4;
    e INT := b % 4;
    f INT := (b + 8) / 25;
    g INT := (b - f + 1) / 3;
    h INT := (19 * a + b - d - g + 15) % 30;
    i INT := c / 4;
    k INT := c % 4;
    l INT := (32 + 2 * e + 2 * i - h - k) % 7;
    m INT := (a + 11 * h + 22 * l) / 451;
BEGIN
    RETURN make_date(y, (h + l - 7 * m + 114) / 31, ((h + l - 7 * m + 114) % 31) + 1);
END;
$$;

-- German nationwide public holidays for one year.
CREATE OR REPLACE FUNCTION german_public_holidays(y INTEGER)
RETURNS TABLE (holiday_date DATE, holiday_name VARCHAR(40))
LANGUAGE sql IMMUTABLE AS $$
    SELECT * FROM (VALUES
        (make_date(y, 1, 1),            'New Year''s Day'::VARCHAR(40)),
        (easter_sunday(y) - 2,          'Good Friday'),
        (easter_sunday(y) + 1,          'Easter Monday'),
        (make_date(y, 5, 1),            'Labour Day'),
        (easter_sunday(y) + 39,         'Ascension Day'),
        (easter_sunday(y) + 50,         'Whit Monday'),
        (make_date(y, 10, 3),           'German Unity Day'),
        (make_date(y, 12, 25),          'Christmas Day'),
        (make_date(y, 12, 26),          'Second Day of Christmas')
    ) AS h (holiday_date, holiday_name);
$$;

CREATE OR REPLACE PROCEDURE fill_dim_date(p_start DATE, p_end DATE)
LANGUAGE sql AS $$
    INSERT INTO dim_date (
        date_key, date, year, quarter, month, month_name, year_month, week,
        weekday, weekday_name, is_weekend, season, is_public_holiday, holiday_name
    )
    SELECT
        to_char(d, 'YYYYMMDD')::INT,
        d,
        EXTRACT(YEAR FROM d)::SMALLINT,
        EXTRACT(QUARTER FROM d)::SMALLINT,
        EXTRACT(MONTH FROM d)::SMALLINT,
        trim(to_char(d, 'FMMonth')),             -- English month name (lc_time = C)
        to_char(d, 'YYYY-MM'),
        EXTRACT(WEEK FROM d)::SMALLINT,          -- ISO 8601 week
        EXTRACT(ISODOW FROM d)::SMALLINT,
        trim(to_char(d, 'FMDay')),
        EXTRACT(ISODOW FROM d) IN (6, 7),
        CASE WHEN EXTRACT(MONTH FROM d) IN (12, 1, 2) THEN 'Winter'
             WHEN EXTRACT(MONTH FROM d) IN (3, 4, 5)  THEN 'Spring'
             WHEN EXTRACT(MONTH FROM d) IN (6, 7, 8)  THEN 'Summer'
             ELSE 'Autumn' END,
        h.holiday_date IS NOT NULL,
        h.holiday_name
    FROM generate_series(p_start, p_end, INTERVAL '1 day') AS g (ts)
    CROSS JOIN LATERAL (SELECT g.ts::DATE AS d) AS x
    LEFT JOIN LATERAL german_public_holidays(EXTRACT(YEAR FROM x.d)::INT) AS h
           ON h.holiday_date = x.d
    ON CONFLICT (date_key) DO UPDATE
    SET is_public_holiday = EXCLUDED.is_public_holiday,
        holiday_name      = EXCLUDED.holiday_name,
        season            = EXCLUDED.season;
$$;
