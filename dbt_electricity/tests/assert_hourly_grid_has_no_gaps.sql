-- Consecutive UTC hours in the mart must be exactly one hour apart.
select timestamp_utc, step
from (
    select timestamp_utc,
           timestamp_utc - lag(timestamp_utc) over (order by timestamp_utc) as step
    from {{ ref('fct_market_hourly') }}
) s
where step <> interval '1 hour'
