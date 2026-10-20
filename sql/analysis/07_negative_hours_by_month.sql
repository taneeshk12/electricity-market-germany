-- Q3: When do negative prices occur? Negative-price hours per month, with their average price.
-- Months without negative hours are included (LEFT JOIN on the full month list) so the series has no gaps.
WITH months AS (SELECT DISTINCT year_month FROM dim_date),
neg AS (
    SELECT dd.year_month,
           COUNT(*)                     AS negative_hours,
           AVG(p.price_eur_mwh)         AS avg_negative_price,
           MIN(p.price_eur_mwh)         AS min_price
    FROM fact_price_load p
    JOIN dim_date dd USING (date_key)
    WHERE p.price_eur_mwh < 0
    GROUP BY dd.year_month
)
SELECT
    m.year_month,
    COALESCE(n.negative_hours, 0)       AS negative_hours,
    ROUND(n.avg_negative_price, 2)      AS avg_negative_price_eur_mwh,
    ROUND(n.min_price, 2)               AS min_price_eur_mwh
FROM months m
LEFT JOIN neg n USING (year_month)
ORDER BY m.year_month;
