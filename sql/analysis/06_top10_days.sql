-- Top 10 most expensive and cheapest days (daily average price), with the day's renewable share
-- and holiday/weekend context to explain them.
WITH daily AS (
    SELECT
        dd.date, dd.weekday_name, dd.holiday_name,
        AVG(v.price_eur_mwh)                              AS avg_price,
        SUM(v.renewable_mwh) / SUM(v.total_gen_mwh)       AS renewable_share,
        SUM(v.wind_mwh) / 1e3 / COUNT(*)                  AS avg_wind_gw,
        SUM(v.solar_mwh) / 1e3 / COUNT(*)                 AS avg_solar_gw
    FROM v_hourly v
    JOIN dim_date dd USING (date_key)
    GROUP BY dd.date, dd.weekday_name, dd.holiday_name
),
ranked AS (
    SELECT *,
           RANK() OVER (ORDER BY avg_price DESC) AS rank_expensive,
           RANK() OVER (ORDER BY avg_price ASC)  AS rank_cheapest
    FROM daily
)
SELECT
    CASE WHEN rank_expensive <= 10 THEN 'most expensive' ELSE 'cheapest' END AS list,
    LEAST(rank_expensive, rank_cheapest)                                      AS rank,
    date, weekday_name, COALESCE(holiday_name, '')                            AS holiday,
    ROUND(avg_price, 2)                                                       AS avg_price_eur_mwh,
    ROUND(100 * renewable_share, 1)                                           AS renewable_share_pct,
    ROUND(avg_wind_gw, 1)                                                     AS avg_wind_gw,
    ROUND(avg_solar_gw, 1)                                                    AS avg_solar_gw
FROM ranked
WHERE rank_expensive <= 10 OR rank_cheapest <= 10
ORDER BY list DESC, rank;
