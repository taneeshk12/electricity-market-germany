-- Q3: Negative-price hours by local hour of day, split by season.
SELECT
    h.hour_label,
    COUNT(*) FILTER (WHERE p.price_eur_mwh < 0)                                AS negative_hours_total,
    COUNT(*) FILTER (WHERE p.price_eur_mwh < 0 AND dd.season = 'Spring')       AS spring,
    COUNT(*) FILTER (WHERE p.price_eur_mwh < 0 AND dd.season = 'Summer')       AS summer,
    COUNT(*) FILTER (WHERE p.price_eur_mwh < 0 AND dd.season = 'Autumn')       AS autumn,
    COUNT(*) FILTER (WHERE p.price_eur_mwh < 0 AND dd.season = 'Winter')       AS winter,
    ROUND(100.0 * COUNT(*) FILTER (WHERE p.price_eur_mwh < 0) / COUNT(*), 1)   AS negative_share_pct
FROM fact_price_load p
JOIN dim_date dd USING (date_key)
JOIN dim_hour h  USING (hour_key)
GROUP BY h.hour_key, h.hour_label
ORDER BY h.hour_key;
