-- Hour-of-day attributes (1:1 with public.dim_hour).
select
    hour_key,
    hour_label,
    is_peak_window,
    day_period
from {{ source('warehouse', 'dim_hour') }}
