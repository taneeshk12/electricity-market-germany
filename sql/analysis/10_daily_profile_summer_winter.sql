-- Q4: What does a typical day look like in summer vs. winter?
-- Average price, load, solar and wind per local hour of day (meteorological seasons).
SELECT
    dd.season,
    h.hour_label,
    ROUND(AVG(v.price_eur_mwh), 2)                                            AS avg_price_eur_mwh,
    ROUND(AVG(v.consumption_mwh) / 1e3, 1)                                    AS avg_load_gw,
    ROUND(AVG(v.solar_mwh) / 1e3, 1)                                          AS avg_solar_gw,
    ROUND(AVG(v.wind_mwh) / 1e3, 1)                                           AS avg_wind_gw,
    ROUND(AVG(v.residual_load_mwh) / 1e3, 1)                                  AS avg_residual_load_gw,
    ROUND(100.0 * COUNT(*) FILTER (WHERE v.price_eur_mwh < 0) / COUNT(*), 1)  AS negative_share_pct
FROM v_hourly v
JOIN dim_date dd USING (date_key)
JOIN dim_hour h  USING (hour_key)
WHERE dd.season IN ('Summer', 'Winter')
GROUP BY dd.season, h.hour_key, h.hour_label
ORDER BY dd.season DESC, h.hour_key;   -- Winter first, then Summer
