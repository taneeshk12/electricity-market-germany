-- Q3: Why do negative prices occur? Rate of negative hours by day type, and the average market
-- conditions in negative vs. non-negative hours. Holidays take precedence over weekend.
-- Hypothesis: low demand (weekends/holidays) + high solar at midday -> oversupply.
WITH typed AS (
    SELECT
        v.*,
        CASE WHEN dd.is_public_holiday THEN 'Public holiday'
             WHEN dd.weekday = 7       THEN 'Sunday'
             WHEN dd.weekday = 6       THEN 'Saturday'
             ELSE                           'Weekday' END                  AS day_type,
        v.price_eur_mwh < 0                                                AS is_negative
    FROM v_hourly v
    JOIN dim_date dd USING (date_key)
)
SELECT
    COALESCE(day_type, 'All days')                                         AS day_type,
    COUNT(*)                                                               AS hours,
    COUNT(*) FILTER (WHERE is_negative)                                    AS negative_hours,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_negative) / COUNT(*), 2)       AS negative_share_pct,
    ROUND(AVG(consumption_mwh)   FILTER (WHERE is_negative) / 1e3, 1)      AS load_gw_when_negative,
    ROUND(AVG(consumption_mwh)   FILTER (WHERE NOT is_negative) / 1e3, 1)  AS load_gw_otherwise,
    ROUND(AVG(solar_mwh)         FILTER (WHERE is_negative) / 1e3, 1)      AS solar_gw_when_negative,
    ROUND(AVG(wind_mwh)          FILTER (WHERE is_negative) / 1e3, 1)      AS wind_gw_when_negative,
    ROUND(AVG(residual_load_mwh) FILTER (WHERE is_negative) / 1e3, 1)      AS residual_load_gw_when_negative,
    ROUND(AVG(residual_load_mwh) FILTER (WHERE NOT is_negative) / 1e3, 1)  AS residual_load_gw_otherwise
FROM typed
GROUP BY ROLLUP (day_type)
ORDER BY GROUPING(day_type), negative_share_pct DESC;   -- ROLLUP total ('All days') last
