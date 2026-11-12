-- Local days must have 24 hours, except the last Sunday in March (23) and October (25).
select local_date, hours
from {{ ref('mart_market_daily') }}
where hours <> 24
  and not (
      extract(isodow from local_date) = 7
      and extract(day from local_date) > 24
      and ((extract(month from local_date) = 3 and hours = 23)
        or (extract(month from local_date) = 10 and hours = 25))
  )
