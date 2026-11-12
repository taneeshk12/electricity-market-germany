-- Local calendar attributes (1:1 with public.dim_date).
select
    date_key,
    date,
    year,
    quarter,
    month,
    month_name,
    year_month,
    week as iso_week,
    weekday as iso_weekday,
    weekday_name,
    is_weekend,
    season,
    is_public_holiday,
    holiday_name
from {{ source('warehouse', 'dim_date') }}
