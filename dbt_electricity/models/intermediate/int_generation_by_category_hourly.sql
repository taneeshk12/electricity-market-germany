-- Generation per UTC hour, pivoted into the categories used throughout the analysis.
-- Same definitions as the generation CTE of public.v_hourly (sql/03_views.sql).
select
    g.timestamp_key,
    sum(g.generation_mwh)                                                          as total_gen_mwh,
    sum(g.generation_mwh) filter (where s.category = 'renewable')                  as renewable_mwh,
    sum(g.generation_mwh) filter (where s.is_variable_renewable)                   as variable_renewable_mwh,
    sum(g.generation_mwh) filter (where s.source_name = 'solar')                   as solar_mwh,
    sum(g.generation_mwh) filter (where s.source_name in ('wind_onshore', 'wind_offshore')) as wind_mwh,
    sum(g.generation_mwh) filter (where s.category = 'fossil')                     as fossil_mwh,
    count(*)                                                                       as sources_reporting
from {{ ref('stg_warehouse__generation') }} g
join {{ ref('stg_warehouse__sources') }} s using (source_key)
group by g.timestamp_key
