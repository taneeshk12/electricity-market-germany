-- Long-format generation summed per hour must equal the pivoted hourly total.
select g.timestamp_key
from (
    select timestamp_key, sum(generation_mwh) as total
    from {{ ref('fct_generation_hourly') }}
    group by timestamp_key
) g
full outer join {{ ref('fct_market_hourly') }} m using (timestamp_key)
where g.total is distinct from m.total_gen_mwh
