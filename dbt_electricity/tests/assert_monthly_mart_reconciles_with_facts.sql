-- Monthly totals must equal the totals of the underlying fact tables (no rows lost or doubled).
with facts as (
    select c.year_month,
           sum(p.consumption_mwh) as consumption_mwh,
           count(*)               as hours
    from {{ source('warehouse', 'fact_price_load') }} p
    join {{ source('warehouse', 'dim_date') }} c using (date_key)
    group by c.year_month
),
gen as (
    select c.year_month, sum(f.generation_mwh) as total_gen_mwh
    from {{ source('warehouse', 'fact_hourly') }} f
    join {{ source('warehouse', 'dim_date') }} c using (date_key)
    group by c.year_month
)
select m.year_month
from {{ ref('mart_market_monthly') }} m
full outer join facts f using (year_month)
full outer join gen g using (year_month)
where m.consumption_mwh is distinct from f.consumption_mwh
   or m.hours           is distinct from f.hours
   or m.total_gen_mwh   is distinct from g.total_gen_mwh
