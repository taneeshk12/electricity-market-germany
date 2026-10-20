-- Rolling 7-day average of the daily average day-ahead price (window function).
-- The first 6 days have an incomplete window and are flagged.
WITH daily AS (
    SELECT dd.date, AVG(p.price_eur_mwh) AS daily_avg_price
    FROM fact_price_load p
    JOIN dim_date dd USING (date_key)
    GROUP BY dd.date
)
SELECT
    date,
    ROUND(daily_avg_price, 2)                                                                  AS daily_avg_price,
    ROUND(AVG(daily_avg_price) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS rolling_7d_avg_price,
    COUNT(*) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) < 7                 AS incomplete_window
FROM daily
ORDER BY date;
