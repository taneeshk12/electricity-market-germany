-- One row per UTC hour: price, load, generation mix and calendar attributes side by side.
-- Grain and measures are identical to public.v_hourly (enforced by a dbt test); calendar
-- columns are denormalised so analysts and the NL agent don't need extra joins.
select
    d.timestamp_key,
    d.timestamp_utc,
    d.timestamp_local,
    d.utc_offset_h,
    d.date_key,
    c.date                                   as local_date,
    c.year,
    c.quarter,
    c.month,
    c.month_name,
    c.year_month,
    c.iso_weekday,
    c.weekday_name,
    c.is_weekend,
    c.is_public_holiday,
    c.season,
    d.hour_key                               as hour_of_day,
    h.day_period,
    d.is_peak,
    p.price_eur_mwh,
    p.price_eur_mwh < 0                      as is_negative_price,
    p.consumption_mwh,
    g.total_gen_mwh,
    g.renewable_mwh,
    g.variable_renewable_mwh,
    g.solar_mwh,
    g.wind_mwh,
    g.fossil_mwh,
    g.renewable_mwh / nullif(g.total_gen_mwh, 0)                as renewable_share,
    -- Residual load = demand that wind and solar do not cover; main price driver.
    p.consumption_mwh - coalesce(g.variable_renewable_mwh, 0)   as residual_load_mwh
from {{ ref('stg_warehouse__datetime') }} d
join {{ ref('stg_warehouse__price_load') }} p using (timestamp_key)
join {{ ref('stg_warehouse__calendar') }} c using (date_key)
join {{ ref('stg_warehouse__hours') }} h using (hour_key)
left join {{ ref('int_generation_by_category_hourly') }} g using (timestamp_key)
