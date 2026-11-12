-- The dbt mart must reproduce public.v_hourly exactly (used by Power BI and sql/analysis).
-- Returns every hour that exists on only one side or where any measure differs.
select timestamp_key
from {{ ref('fct_market_hourly') }} m
full outer join {{ source('warehouse', 'v_hourly') }} v using (timestamp_key)
where m.timestamp_key is null
   or v.timestamp_key is null
   or m.price_eur_mwh          is distinct from v.price_eur_mwh
   or m.consumption_mwh        is distinct from v.consumption_mwh
   or m.total_gen_mwh          is distinct from v.total_gen_mwh
   or m.renewable_mwh          is distinct from v.renewable_mwh
   or m.variable_renewable_mwh is distinct from v.variable_renewable_mwh
   or m.renewable_share        is distinct from v.renewable_share
   or m.residual_load_mwh      is distinct from v.residual_load_mwh
   or m.is_peak                is distinct from v.is_peak
