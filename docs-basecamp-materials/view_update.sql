drop view app_log_json;
create view app_log_json as with regular_entries as (
	select
		schedid,
		chg_at modified,
		'main' kind,
		coalesce(chg_by, '')::text chg_by,
		json_strip_nulls(json_build_object(
			'researcher', case 
				when researchercode_old is distinct from researchercode then
					json_build_array(researchercode_old, researchercode)
				else null end,
			'group', case
				when deptcode_old is distinct from deptcode then
					json_build_array(deptcode_old, deptcode)
				else null end,
			'used', case
				when time_used_old is distinct from time_used then
					json_build_array(time_used_old, time_used)
				else null end
		)) as values
	from tlogsched where schedid is not null and chg_at is not null
),
support_entries as (
	select
		schedid,
		chg_at modified,
		label kind,
		chg_by::text,
		json_strip_nulls(json_build_object(
			'filed_by', case 
				when filed_by_old is distinct from filed_by then
					json_build_array(filed_by_old, filed_by)
				else null end,
			'fulfilled_by', case 
				when fulfilled_by_old is distinct from fulfilled_by then
					json_build_array(fulfilled_by_old, fulfilled_by)
				else null end,
			'approved', case 
				when approved_old is distinct from approved then
					json_build_array(approved_old, approved)
				else null end,
			'note', case 
				when note_old is distinct from note then
					json_build_array(note_old, note)
				else null end
		)) as values
	from supportlog
	inner join supportkind using(supportkind)
),
combined_entries as (
	select * from regular_entries
	union all
	select * from support_entries
),
filtered_and_sorted_entries as (
	select schedid, json_build_object('modified', modified, 'kind', kind, 'by', chg_by, 'values', values) entries from combined_entries where length(values::text) > 2 order by modified
)
select schedid, json_agg(entries) entries from filtered_and_sorted_entries
group by schedid;

comment on view app_log_json is 'get json of all log entries - always call with "where schedid = "!';
comment on column app_log_json.schedid is 'the schedid of the log entries - MUST specify this in where clause!';
comment on column app_log_json.entries is 'json of all log entries for selected schedid';
