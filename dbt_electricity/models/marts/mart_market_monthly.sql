-- One row per local calendar month.
select
    year_month,
    year,
    month,
    count(*)                                                      as hours,
    avg(price_eur_mwh)                                            as avg_price_eur_mwh,
    stddev_samp(price_eur_mwh)                                    as price_stddev_eur_mwh,  -- volatility
    min(price_eur_mwh)                                            as min_price_eur_mwh,
    max(price_eur_mwh)                                            as max_price_eur_mwh,
    avg(price_eur_mwh) filter (where is_peak)                     as avg_peak_price_eur_mwh,
    avg(price_eur_mwh) filter (where not is_peak)                 as avg_offpeak_price_eur_mwh,
    count(*) filter (where is_negative_price)                     as negative_price_hours,
    count(*) filter (where is_negative_price)::numeric / count(*) as negative_price_hour_share,
    sum(consumption_mwh)                                          as consumption_mwh,
    max(consumption_mwh)                                          as peak_hourly_load_mwh,
    sum(total_gen_mwh)                                            as total_gen_mwh,
    sum(renewable_mwh)                                            as renewable_mwh,
    sum(solar_mwh)                                                as solar_mwh,
    sum(wind_mwh)                                                 as wind_mwh,
    sum(fossil_mwh)                                               as fossil_mwh,
    sum(renewable_mwh) / nullif(sum(total_gen_mwh), 0)            as renewable_share,
    avg(residual_load_mwh)                                        as avg_residual_load_mwh
from {{ ref('fct_market_hourly') }}
group by year_month, year, month
