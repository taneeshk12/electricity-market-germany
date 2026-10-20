-- Year-over-year comparison of the key KPIs, using LAG() to compute the change vs. the previous year.
WITH yearly AS (
    SELECT
        dd.year,
        AVG(v.price_eur_mwh)                                          AS avg_price,
        SUM(v.renewable_mwh) / SUM(v.total_gen_mwh)                   AS renewable_share,
        SUM(v.total_gen_mwh) / 1e6                                    AS generation_twh,
        SUM(v.consumption_mwh) / 1e6                                  AS load_twh,
        COUNT(*) FILTER (WHERE v.price_eur_mwh < 0)                   AS negative_hours
    FROM v_hourly v
    JOIN dim_date dd USING (date_key)
    GROUP BY dd.year
)
SELECT
    year,
    ROUND(avg_price, 2)                                                           AS avg_price_eur_mwh,
    ROUND(100 * (avg_price / LAG(avg_price) OVER w - 1), 1)                       AS avg_price_yoy_pct,
    ROUND(100 * renewable_share, 1)                                               AS renewable_share_pct,
    ROUND(100 * (renewable_share - LAG(renewable_share) OVER w), 1)               AS renewable_share_yoy_pp,
    ROUND(generation_twh, 1)                                                      AS generation_twh,
    ROUND(load_twh, 1)                                                            AS load_twh,
    ROUND(100 * (load_twh / LAG(load_twh) OVER w - 1), 1)                         AS load_yoy_pct,
    negative_hours,
    ROUND(100.0 * (negative_hours::NUMERIC / LAG(negative_hours) OVER w - 1), 1)  AS negative_hours_yoy_pct
FROM yearly
WINDOW w AS (ORDER BY year)
ORDER BY year;
