-- Hourly time axis: UTC key + local wall clock (1:1 with public.dim_datetime).
select
    timestamp_key,
    timestamp_utc,
    timestamp_local,
    utc_offset_h,
    date_key,
    hour_key,
    is_peak
from {{ source('warehouse', 'dim_datetime') }}
