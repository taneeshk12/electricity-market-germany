-- =============================================================================
-- 03_views.sql – Analysis view at UTC-hour grain
--
-- v_hourly joins both fact tables on timestamp_key so every hour has price,
-- load and the generation mix side by side. Shares are computed per hour;
-- aggregates over longer periods should be energy-weighted
-- (SUM(renewable) / SUM(total)), not averages of hourly shares.
--
-- Note: in the 20 hours where a single source has no value, total generation
-- is slightly understated (documented in docs/data_quality_report.md).
-- =============================================================================

CREATE OR REPLACE VIEW v_hourly AS
WITH gen AS (
    SELECT
        f.timestamp_key,
        SUM(f.generation_mwh)                                                     AS total_gen_mwh,
        SUM(f.generation_mwh) FILTER (WHERE s.category = 'renewable')             AS renewable_mwh,
        SUM(f.generation_mwh) FILTER (WHERE s.is_variable_renewable)              AS variable_renewable_mwh,
        SUM(f.generation_mwh) FILTER (WHERE s.source_name = 'solar')              AS solar_mwh,
        SUM(f.generation_mwh) FILTER (WHERE s.source_name IN ('wind_onshore', 'wind_offshore')) AS wind_mwh,
        SUM(f.generation_mwh) FILTER (WHERE s.category = 'fossil')                AS fossil_mwh
    FROM fact_hourly f
    JOIN dim_source s USING (source_key)
    GROUP BY f.timestamp_key
)
SELECT
    d.timestamp_key,
    d.timestamp_utc,
    d.timestamp_local,
    d.date_key,
    d.hour_key,
    d.is_peak,
    p.price_eur_mwh,
    p.consumption_mwh,
    g.total_gen_mwh,
    g.renewable_mwh,
    g.variable_renewable_mwh,
    g.solar_mwh,
    g.wind_mwh,
    g.fossil_mwh,
    g.renewable_mwh / NULLIF(g.total_gen_mwh, 0)                    AS renewable_share,
    -- Residual load = demand that wind and solar do not cover; classic price driver.
    p.consumption_mwh - COALESCE(g.variable_renewable_mwh, 0)       AS residual_load_mwh
FROM dim_datetime d
JOIN fact_price_load p USING (timestamp_key)
LEFT JOIN gen g USING (timestamp_key);
