# Power BI setup guide: connecting to PostgreSQL

## 0. Where to run Power BI Desktop

Power BI Desktop runs **only on Windows**. The database runs in Docker on the Mac. Options:

| Option | Server address to use in Power BI |
|---|---|
| Windows VM on the Mac (Parallels, VMware Fusion, UTM) | The Mac as seen from the VM, e.g. Parallels "Shared network": `10.211.55.2:5433`. Find it in Windows with `ipconfig` (default gateway). |
| Separate Windows PC in the same network | The Mac's LAN IP (System Settings > Network), e.g. `192.168.1.20:5433` |
| Everything on one Windows machine | Run the pipeline there too, then use `localhost:5433` |

Docker publishes port 5433 on all network interfaces, so the VM or PC can reach it. If macOS asks
whether Docker may accept incoming connections, allow it. Quick test from Windows PowerShell:
`Test-NetConnection 10.211.55.2 -Port 5433` should report `TcpTestSucceeded : True`.

> If you only ever connect from the Mac itself, restrict the port to localhost in
> `docker-compose.yml`: `"127.0.0.1:${POSTGRES_PORT:-5433}:5432"`.

## 1. (Recommended) Create a read-only user for reporting

Power BI should not use the owner account that the pipeline writes with. Run `make db-shell` and
choose your own password:

```sql
CREATE ROLE powerbi_reader LOGIN PASSWORD '<choose-a-password>';
GRANT CONNECT ON DATABASE electricity TO powerbi_reader;
GRANT USAGE ON SCHEMA public TO powerbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO powerbi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO powerbi_reader;
```

## 2. Connect

1. Power BI Desktop > **Home > Get data > More… > Database > PostgreSQL database**.
2. **Server:** `<address>:5433` (address from step 0). **Database:** `electricity`.
   **Data connectivity mode:** *Import*. Click OK.
3. Credentials: choose the **Database** tab, user `powerbi_reader` (or `emg`), and the password.
4. **If you get an SSL/encryption error:** the Docker Postgres does not use SSL. Go to
   *File > Options and settings > Data source settings*, select the source, click *Edit permissions*,
   **uncheck "Encrypt connections"**, and connect again. This is fine on a local network; production
   databases should use SSL.
5. In the Navigator, tick these 6 tables: `public.dim_date`, `public.dim_hour`, `public.dim_source`,
   `public.dim_datetime`, `public.fact_hourly`, `public.fact_price_load`. Do **not** load `v_hourly`
   (it duplicates the facts; it exists for SQL analysis). Click **Transform Data**.

## 3. Power Query (Transform Data)

1. Rename the queries so they drop the `public ` prefix (e.g. `public dim_date` → `dim_date`).
2. Check the data types (PostgreSQL types usually map automatically):
   - `*_key` columns → Whole number
   - `generation_mwh`, `consumption_mwh`, `price_eur_mwh` → Decimal number
   - `dim_date[date]` → Date; `dim_datetime[timestamp_local]` → Date/Time; `timestamp_utc` → Date/Time/Timezone
   - `is_*` columns → True/False
3. **Close & Apply**.

## 4. Model setup

1. **File > Options > Current file > Data load:** turn **off** "Auto date/time" (the model has its own
   date table; the automatic hidden tables only bloat the file).
2. **Model view > Manage relationships:** delete everything Power BI auto-detected, then create the
   7 relationships from [`report_spec.md`](report_spec.md#data-model) (all many-to-one, single direction).
   Make sure there is **no** relationship between dim_datetime and dim_date or dim_hour.
3. **Mark as date table:** select `dim_date` > Table tools > *Mark as date table* > column `date`.
4. **Sort by column** (Column tools > Sort by column):
   - `dim_date[month_name]` by `dim_date[month]`
   - `dim_date[weekday_name]` by `dim_date[weekday]`
   - `dim_hour[hour_label]` by `dim_hour[hour_key]`
5. **Hide** in report view (right-click > Hide in report view): all `*_key` columns in the two fact
   tables, `dim_source[smard_filter_id]`, and `dim_datetime[timestamp_utc]`.
6. **Measures:** Home > *Enter data* > name the table `_Measures` > Load. Add every measure from
   [`measures.dax`](measures.dax) (Modeling > New measure), then delete the dummy column. Put
   measures in the suggested display folders (Properties pane).
7. **Calculated columns:** add `Day Type` and `Day Type Order` (dim_date), `Hourly Renewable Share`
   and `Renewable Share Bucket` (dim_datetime), and `Price Sign` (fact_price_load) from the same
   file (Modeling > New column). Set *Sort by column* for `Day Type` to `Day Type Order`.
8. **Formats** (Measure tools): shares as Percentage with 1 decimal, prices as decimals with 2
   places, `Renewable Share YoY pp` as decimal with 1 place.

## 5. Validate before building visuals

Build a temporary table with `dim_date[year]` and the measures from the
[validation checklist](report_spec.md#validation-checklist). Every value must match the SQL
results. If one doesn't, it's almost always a relationship (step 4.2) or the date table (step 4.3).

## 6. Refresh after re-running the pipeline

`make pipeline` reloads the database idempotently; then press **Home > Refresh** in Power BI.
Save the report as `powerbi/electricity_market.pbix`. `.pbix` files are gitignored, so commit
screenshots (e.g. `docs/img/page1.png`) instead.
