begin;

-- remove constraints for deprecated column
alter table tlkpresearcher drop constraint tlkpresearcher_dept_code_fkey;
alter table tlkpresearcher drop constraint tlkpresearcher_dept_code_key;

-- add a way to mark researchers inactive
alter table tlkpresearcher add column active boolean not null default true;

-- rebuild records for missing researchers and mark them as inactive

-- need these aggregate functions from the postgres wiki for the next step:

create function last_set_agg(anyelement, anyelement) returns anyelement language sql immutable strict parallel safe as $$
	select coalesce($2, $1);
$$;
create aggregate last_set (
	sfunc = last_set_agg,
	basetype = anyelement,
	stype = anyelement
);

with
	names as (
		-- get all unique names in sched, template that aren't in researcher table
		select distinct researchercode from (
			select researchercode from tblsched
			union all
			select researchercode from tbltemplate
		) as N where researchercode is not null and not exists (
			select * from tlkpresearcher R where N.researchercode = R.researchercode
		)
	),
	last_ref as (
		-- get last entries in log for above names, if they exist
		select
			researchercode,
			coalesce(last_set(lname), '<none>') lname,
			coalesce(last_set(fname), '<none>') fname,
			coalesce(last_set(researchershort), researchercode) researchershort,
			last_set(chg_at) chg_at,
			'migration' chg_by,
			false as active
		from tlogresearcher log
		where exists (select * from names where names.researchercode = log.researchercode)
		group by researchercode
		order by chg_at
	)
insert into tlkpresearcher(researchercode, lname, fname, researchershort, chg_at, chg_by, active) select * from last_ref;

-- only needed these for that one query
drop aggregate last_set(anyelement);
drop function last_set_agg;

-- there are still missing researchers but we only really need the researchercode so we make everything else up
with
	names as (
		-- get all unique names in sched, template that still aren't in researcher table
		select distinct researchercode from (
			select researchercode from tblsched
			union all
			select researchercode from tbltemplate
		) as N where researchercode is not null and not exists (
			select * from tlkpresearcher R where N.researchercode = R.researchercode
		)
	),
	tup as (
		-- prepare default values for insert
		select researchercode, '<none>', '<none>', researchercode, '-infinity'::timestamp(6) without time zone, 'migration', false from names
	)
insert into tlkpresearcher(researchercode, lname, fname, researchershort, chg_at, chg_by, active) select * from tup;

-- now that all the necessary researchers exist, we can add fk constraints

alter table tblsched add constraint tblsched_researchercode_fkey foreign key (researchercode) references tlkpresearcher(researchercode) on update cascade on delete restrict;
alter table tbltemplate add constraint tbltemplate_researchercode_fkey foreign key (researchercode) references tlkpresearcher(researchercode) on update cascade on delete restrict;

commit;