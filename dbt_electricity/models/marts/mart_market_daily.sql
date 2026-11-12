-- One row per local (Europe/Berlin) day. Shares are energy-weighted, not means of hourly shares.
select
    local_date,
    year,
    month,
    year_month,
    weekday_name,
    is_weekend,
    is_public_holiday,
    season,
    count(*)                                              as hours,       -- 23 / 25 on DST days
    avg(price_eur_mwh)                                    as avg_price_eur_mwh,
    min(price_eur_mwh)                                    as min_price_eur_mwh,
    max(price_eur_mwh)                                    as max_price_eur_mwh,
    count(*) filter (where is_negative_price)             as negative_price_hours,
    sum(consumption_mwh)                                  as consumption_mwh,
    max(consumption_mwh)                                  as peak_hourly_load_mwh,
    sum(total_gen_mwh)                                    as total_gen_mwh,
    sum(renewable_mwh)                                    as renewable_mwh,
    sum(renewable_mwh) / nullif(sum(total_gen_mwh), 0)    as renewable_share,
    avg(residual_load_mwh)                                as avg_residual_load_mwh
from {{ ref('fct_market_hourly') }}
group by local_date, year, month, year_month, weekday_name, is_weekend, is_public_holiday, season
