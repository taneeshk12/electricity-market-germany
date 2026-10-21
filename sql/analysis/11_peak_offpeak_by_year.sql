-- Peak vs. off-peak price per year. Peak = Mon–Fri 08:00–20:00 local (EEX definition, dim_datetime.is_peak).
-- Also shows the load-weighted price (what an average consumed MWh cost) next to the time-weighted average.
SELECT
    COALESCE(dd.year::TEXT, 'All years')                                               AS year,
    ROUND(AVG(p.price_eur_mwh) FILTER (WHERE d.is_peak), 2)                            AS peak_price_eur_mwh,
    ROUND(AVG(p.price_eur_mwh) FILTER (WHERE NOT d.is_peak), 2)                        AS offpeak_price_eur_mwh,
    ROUND(AVG(p.price_eur_mwh) FILTER (WHERE d.is_peak)
        - AVG(p.price_eur_mwh) FILTER (WHERE NOT d.is_peak), 2)                        AS peak_spread_eur_mwh,
    ROUND(AVG(p.price_eur_mwh), 2)                                                     AS avg_price_eur_mwh,
    ROUND(SUM(p.price_eur_mwh * p.consumption_mwh) / SUM(p.consumption_mwh), 2)        AS load_weighted_price_eur_mwh
FROM fact_price_load p
JOIN dim_datetime d USING (timestamp_key)
JOIN dim_date dd ON dd.date_key = p.date_key
GROUP BY ROLLUP (dd.year)
ORDER BY dd.year NULLS LAST;
