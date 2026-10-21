# Data model

Star schema in PostgreSQL (DDL: [`sql/01_schema.sql`](../sql/01_schema.sql), calendar:
[`sql/02_dim_date.sql`](../sql/02_dim_date.sql), analysis view: [`sql/03_views.sql`](../sql/03_views.sql)).

```mermaid
erDiagram
    fact_hourly {
        bigint   timestamp_key PK, FK "yyyymmddhh UTC"
        smallint source_key    PK, FK
        int      date_key      FK "local date"
        smallint hour_key      FK "local hour"
        numeric  generation_mwh
    }
    fact_price_load {
        bigint   timestamp_key PK, FK
        int      date_key      FK
        smallint hour_key      FK
        numeric  price_eur_mwh
        numeric  consumption_mwh
    }
    dim_date {
        int     date_key PK "yyyymmdd"
        date    date
        int     year
        int     quarter
        int     month
        text    month_name
        int     week "ISO"
        int     weekday "1 = Mon"
        bool    is_weekend
        text    season "meteorological"
        bool    is_public_holiday "nationwide"
        text    holiday_name
    }
    dim_hour {
        smallint hour_key PK "0-23"
        text     hour_label
        bool     is_peak_window "08-20"
        text     day_period
    }
    dim_source {
        smallint source_key PK
        text     source_name
        text     category "renewable/fossil/nuclear/other"
        bool     is_variable_renewable "wind, solar"
        int      smard_filter_id
    }
    dim_datetime {
        bigint    timestamp_key PK
        timestamptz timestamp_utc
        timestamp timestamp_local
        smallint  utc_offset_h "1 CET, 2 CEST"
        bool      is_peak "Mon-Fri 08-20"
    }

    dim_date     ||--o{ fact_hourly     : ""
    dim_hour     ||--o{ fact_hourly     : ""
    dim_source   ||--o{ fact_hourly     : ""
    dim_datetime ||--o{ fact_hourly     : ""
    dim_date     ||--o{ fact_price_load : ""
    dim_hour     ||--o{ fact_price_load : ""
    dim_datetime ||--o{ fact_price_load : ""
```

## Tables

| Table | Grain | Rows | Notes |
|---|---|---|---|
| fact_hourly | UTC hour × source | 298,792 | 12 sources × 26,304 h minus 16,856 rows without a value (nuclear after its series ended, 20 incomplete hours) |
| fact_price_load | UTC hour | 26,304 | complete; price NUMERIC(10,4) because post-Oct-2025 hours are means of 4 quarter-hour prices |
| dim_date | local day | 1,096 | 27 holidays (9 nationwide × 3 years), computed in SQL from an Easter function |
| dim_hour | local hour of day | 24 | |
| dim_source | generation source | 12 | fixed keys; pumped storage = `other`, "other conventional" = `fossil` |
| dim_datetime | UTC hour | 26,304 | peak flag; unique even on the 25-hour DST day |

## Source classification

| Category | Sources |
|---|---|
| renewable (variable) | wind onshore, wind offshore, solar |
| renewable | biomass, hydro, other renewables |
| fossil | lignite, hard coal, natural gas, other conventional |
| nuclear | nuclear (last generation 2023-04-15) |
| other | pumped storage (a storage technology, not primary generation) |
