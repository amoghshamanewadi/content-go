--SQL file to perform basic aggregations and joins on the datasets provided

--Findings from data profiling:
--1. main dataset analytical_task_dim_learning_object
--2. Group findings by cp_portal_id (unique Content Partner identifier)
--3. And then include lo_topic_name for analysis by course
--4. Restrict to only active learning objects (lo_decommissioned_ts is null)
--5. Restrict to only cp_is_premium=true (premium content partners)
--6. Other columns of interest: lo_type, lo_has_compliance_topic, lo_is_english
--7. Old Learning Minutes dataset is aggregated to monthly level, new learning minutes dataset is aggregated to daily level. Aggregate new learning minutes to monthly level to compare with old learning minutes
--8. New Learning Minutes dataset has data only for Jan-2024. So good to aggregate all
--9. New Learning Minutes dataset has an additional column enrolment_id. Ignoring for now
--10. IMPORTANT: Unsure about capped minutes calculation. For now, summing up minutes assuming direct aggregation is valid. 

--Aggregate new learning minutes to monthly level
--91,378 Vs old:1,672,373 rows. old minutes dataset has 88,040 rows. So some learning objects are missing in the old minutes dataset. Need to investigate further. 

with new_learning_minutes_monthly as
(
select
lo_id
, '2024-01-01' as activity_month
, sum(learning_minutes_capped_new) as learning_minutes_capped_new

from analytical_Task_new_learning_minute_data_daily
group by all
)
, old_learning_minutes_monthly as
(
select
lo_id
, date(activity_month) as activity_month
, learning_minutes_capped_old

from analytical_task_old_learning_minute_data
)
, joined_learning_minutes as
(
select 
a.lo_id
, a.activity_month
, a.learning_minutes_capped_new
, b.learning_minutes_capped_old

from new_learning_minutes_monthly a
left join old_learning_minutes_monthly b
on a.lo_id=b.lo_id and a.activity_month=b.activity_month

)
select *
,  100.0 * sum(learning_minutes_capped_new)
    / nullif(sum(sum(learning_minutes_capped_new)) over (), 0) as pct_of_total_new_learning_minutes
, 100.0 * sum(learning_minutes_capped_old)
    / nullif(sum(sum(learning_minutes_capped_old)) over (), 0) as pct_of_total_old_learning_minutes
 from joined_learning_minutes
 group by all
;

--Data checks:
--4650 rows where old learning minutes is null

with new_learning_minutes_monthly as
(
select
lo_id
, '2024-01-01' as activity_month
, sum(learning_minutes_capped_new) as learning_minutes_capped_new

from analytical_Task_new_learning_minute_data_daily
group by all
)
, old_learning_minutes_monthly as
(
select
lo_id
, date(activity_month) as activity_month
, learning_minutes_capped_old

from analytical_task_old_learning_minute_data
)
, joined_learning_minutes as
(
select 
a.lo_id
, a.activity_month
, a.learning_minutes_capped_new
, b.learning_minutes_capped_old

from new_learning_minutes_monthly a
left join old_learning_minutes_monthly b
on a.lo_id=b.lo_id and a.activity_month=b.activity_month
),
checks as
(
select *
 from joined_learning_minutes
where learning_minutes_capped_old is null
)
select count(*) from checks
;



-- Join with analytical_task_dim_learning_object to get cp_portal_id and lo_topic_name for analysis by course
--This is the base table for analysis. 


copy
(
with 
base as 
(
select
cp_portal_id
, lo_id
, lo_is_english
, lo_type
, lo_has_compliance_topic
, lo_decommissioned_ts
, lo_topic_name
, cp_is_premium

from analytical_task_dim_learning_object 
)
,new_learning_minutes_monthly as
(
select
lo_id
, '2024-01-01' as activity_month
, sum(learning_minutes_capped_new) as learning_minutes_capped_new

from analytical_Task_new_learning_minute_data_daily
group by all
)
, old_learning_minutes_monthly as
(
select
lo_id
, date(activity_month) as activity_month
, learning_minutes_capped_old

from analytical_task_old_learning_minute_data
)
, joined_learning_minutes as
(
select 
a.lo_id
, a.activity_month
, a.learning_minutes_capped_new
, b.learning_minutes_capped_old

from new_learning_minutes_monthly a
left join old_learning_minutes_monthly b
on a.lo_id=b.lo_id and a.activity_month=b.activity_month

)
, new_old_Joined as
(
select *
,  100.0 * sum(learning_minutes_capped_new)
    / nullif(sum(sum(learning_minutes_capped_new)) over (), 0) as pct_of_total_new_learning_minutes
, 100.0 * sum(learning_minutes_capped_old)
    / nullif(sum(sum(learning_minutes_capped_old)) over (), 0) as pct_of_total_old_learning_minutes
 from joined_learning_minutes
 group by all
)
    select  
    a.*
    , b.learning_minutes_capped_new
    , b.learning_minutes_capped_old
    , b.pct_of_total_new_learning_minutes
    , b.pct_of_total_old_learning_minutes

    from base a
    left join new_old_Joined b
    on a.lo_id=b.lo_id
where 
learning_minutes_capped_new
is not null 
or learning_minutes_capped_old is not null
)
TO 'outputs/tables/All_ds_joined_no_nulls.csv'
WITH (HEADER, DELIMITER ',')
