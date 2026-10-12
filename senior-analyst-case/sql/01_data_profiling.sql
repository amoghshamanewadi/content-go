--SQL file used for data profiling of the datasets provided

/*******************************************************************************************
Begin First dataset: analytical_task_dim_learning_object
*******************************************************************************************/
--SHOW TABLES;

select count(*) from analytical_task_dim_learning_object;
--2736919 rows

desc table analytical_task_dim_learning_object;


select lo_type, count(*) as cnt
from analytical_task_dim_learning_object
group by lo_type
order by cnt desc;


select max(lo_duration_in_minutes) as max_duration, min(lo_duration_in_minutes) as min_duration, avg(lo_duration_in_minutes) as avg_duration
from analytical_task_dim_learning_object
where lo_duration_in_minutes<180;


--Decommissioned vs Active Learning Objects
select 
case when lo_decommissioned_ts is not null then 'Decommissioned' else 'Active' end as status,
count(*) as cnt
 from analytical_task_dim_learning_object
group by 1;

--Premium Vs non Premium: 705,096 premium and 2,031,823 non premium
select cp_is_premium, count(*) as cnt
from analytical_task_dim_learning_object
group by 1;


select min(lo_created_ts) as min_created_ts, max(lo_created_ts) as max_created_ts from analytical_task_dim_learning_object;
--min_created_ts: 1970-01-01, max_created_ts: 2024-04-09 00:56:14

--**** 8,114 rows have lo_created_ts as 1970-01-01, which is likely a default value for missing data. This needs to be handled in the analysis
select lo_created_ts, count(*) as cnt
from analytical_task_dim_learning_object
where date(lo_created_ts)='1970-01-01'
group by 1
;

--
--select min(lo_updated_ts) as min_updated_ts, max(lo_updated_ts) as max_updated_ts from analytical_task_dim_learning_object;


--No duplicates found for lo_id
--Check for duplicates by lo_id
with base as
(
select lo_id, count(*) as cnt
from analytical_task_dim_learning_object
group by 1
order by cnt desc
)
select count(*) from base where cnt>1
;



--Random check from CSV file
select * from analytical_task_dim_learning_object
where lo_id=36443071

--lo_id is unique. Group by cp_portal_id for analysis

with base as
(
select lo_id
, count(*) as cnt
from analytical_task_dim_learning_object
group by 1
order by cnt desc
)
select * from base where cnt>1
;


/*******************************************************************************************
END
*******************************************************************************************/



/*******************************************************************************************
BEGIN: Second dataset: analytical_Task_new_learning_minute_data_daily
*******************************************************************************************/

desc table analytical_Task_new_learning_minute_data_daily;
--Columns: activity_date, enrolment_id, lo_id, learning_minutes_capped_new

select count(*) from analytical_Task_new_learning_minute_data_daily;
--1,672,373 rows

--All data from 2024-01
select count(*) from analytical_Task_new_learning_minute_data_daily
where month(activity_date) <> 1 and year(activity_date) <> 2024;


/*******************************************************************************************
END
*******************************************************************************************/





/*******************************************************************************************
BEGIN: Third dataset: analytical_task_old_learning_minute_data
*******************************************************************************************/

--desc table analytical_task_old_learning_minute_data
--Columns: activity_month,lo_id, learning_minutes_capped_old
--***** Old minutes calculation aggregated to monthly level, new minutes calculation aggregated to daily level
--***** Aggregate new learning minutes to monthly level to compare with old learning minutes

select count(*) from analytical_task_old_learning_minute_data;
--88,040 rows
--Just one activity month: 2024-01-01
select distinct activity_month from analytical_task_old_learning_minute_data;

/*******************************************************************************************
END: Third dataset: analytical_task_old_learning_minute_data
*******************************************************************************************/