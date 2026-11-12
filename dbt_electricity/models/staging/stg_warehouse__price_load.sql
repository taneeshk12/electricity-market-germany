-- Hourly day-ahead price and grid load (1:1 with public.fact_price_load).
select
    timestamp_key,
    price_eur_mwh,
    consumption_mwh
from {{ source('warehouse', 'fact_price_load') }}
