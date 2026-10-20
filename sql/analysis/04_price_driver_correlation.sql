-- Q2 (quantified): correlation and simple linear slope between price and its drivers, per year.
-- corr() = Pearson correlation; regr_slope() = EUR/MWh change per additional GW (1 GW for 1 h = 1,000 MWh).
-- Residual load (load minus wind and solar) captures demand AND renewables in one variable.
SELECT
    COALESCE(dd.year::TEXT, 'All years')                                              AS year,
    ROUND(CORR(v.price_eur_mwh, v.renewable_share)::NUMERIC, 3)                        AS corr_price_renewable_share,
    ROUND(CORR(v.price_eur_mwh, v.variable_renewable_mwh)::NUMERIC, 3)                 AS corr_price_wind_solar,
    ROUND(CORR(v.price_eur_mwh, v.consumption_mwh)::NUMERIC, 3)                        AS corr_price_load,
    ROUND(CORR(v.price_eur_mwh, v.residual_load_mwh)::NUMERIC, 3)                      AS corr_price_residual_load,
    ROUND(REGR_SLOPE(v.price_eur_mwh, v.variable_renewable_mwh / 1000)::NUMERIC, 2)    AS eur_per_gw_wind_solar,
    ROUND(REGR_SLOPE(v.price_eur_mwh, v.residual_load_mwh / 1000)::NUMERIC, 2)         AS eur_per_gw_residual_load,
    ROUND(REGR_R2(v.price_eur_mwh, v.residual_load_mwh)::NUMERIC, 3)                   AS r2_residual_load
FROM v_hourly v
JOIN dim_date dd USING (date_key)
GROUP BY ROLLUP (dd.year)
ORDER BY dd.year NULLS LAST;   -- ROLLUP adds the 'All years' total row
