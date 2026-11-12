-- Generation source classification (1:1 with public.dim_source).
select
    source_key,
    source_name,
    source_label,
    category,
    is_variable_renewable,
    smard_filter_id
from {{ source('warehouse', 'dim_source') }}
