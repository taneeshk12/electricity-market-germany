-- Q2: How strongly does renewable generation affect the price?
-- Hours bucketed by their renewable share (20 %-buckets); average/median price and share of negative hours.
SELECT
    CASE WHEN renewable_share < 0.2 THEN '0–20 %'
         WHEN renewable_share < 0.4 THEN '20–40 %'
         WHEN renewable_share < 0.6 THEN '40–60 %'
         WHEN renewable_share < 0.8 THEN '60–80 %'
         ELSE                            '80–100 %' END                              AS renewable_share_bucket,
    COUNT(*)                                                                          AS hours,
    ROUND(AVG(price_eur_mwh), 2)                                                      AS avg_price_eur_mwh,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_eur_mwh)::NUMERIC, 2)     AS median_price_eur_mwh,
    ROUND(100.0 * COUNT(*) FILTER (WHERE price_eur_mwh < 0) / COUNT(*), 1)            AS negative_hours_pct
FROM v_hourly
WHERE renewable_share IS NOT NULL
GROUP BY 1
ORDER BY 1;
