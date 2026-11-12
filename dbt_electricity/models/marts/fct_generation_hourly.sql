-- Long-format generation per UTC hour and source, with source labels and local calendar.
select
    g.timestamp_key,
    d.timestamp_utc,
    d.timestamp_local,
    c.date                    as local_date,
    c.year,
    c.month,
    c.year_month,
    d.hour_key                as hour_of_day,
    s.source_name,
    s.source_label,
    s.category,
    s.is_variable_renewable,
    g.generation_mwh
from {{ ref('stg_warehouse__generation') }} g
join {{ ref('stg_warehouse__datetime') }} d using (timestamp_key)
join {{ ref('stg_warehouse__calendar') }} c using (date_key)
join {{ ref('stg_warehouse__sources') }} s using (source_key)
