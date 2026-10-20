-- Q1: How has the renewable share developed over time?
-- Monthly renewable share of net generation, energy-weighted (sum of MWh, not average of hourly shares),
-- with wind and solar split out. Months are local (Europe/Berlin) calendar months.
SELECT
    dd.year_month,
    ROUND(SUM(f.generation_mwh) / 1e6, 2)                                                     AS generation_twh,
    ROUND(100 * SUM(f.generation_mwh) FILTER (WHERE s.category = 'renewable') / SUM(f.generation_mwh), 1)
                                                                                              AS renewable_share_pct,
    ROUND(100 * SUM(f.generation_mwh) FILTER (WHERE s.source_name IN ('wind_onshore', 'wind_offshore'))
              / SUM(f.generation_mwh), 1)                                                     AS wind_share_pct,
    ROUND(100 * SUM(f.generation_mwh) FILTER (WHERE s.source_name = 'solar') / SUM(f.generation_mwh), 1)
                                                                                              AS solar_share_pct,
    ROUND(100 * SUM(f.generation_mwh) FILTER (WHERE s.category = 'fossil') / SUM(f.generation_mwh), 1)
                                                                                              AS fossil_share_pct
FROM fact_hourly f
JOIN dim_source s USING (source_key)
JOIN dim_date   dd USING (date_key)
GROUP BY dd.year_month
ORDER BY dd.year_month;
