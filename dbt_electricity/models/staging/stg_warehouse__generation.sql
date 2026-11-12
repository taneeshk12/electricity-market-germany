-- Hourly net generation per source (1:1 with public.fact_hourly).
select
    timestamp_key,
    source_key,
    generation_mwh
from {{ source('warehouse', 'fact_hourly') }}
