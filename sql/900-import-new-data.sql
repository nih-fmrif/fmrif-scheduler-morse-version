begin;

-- This importer performs relationship hydration from CSV mappings
-- onto the post-migration auth/relationship model.
-- It creates required placeholder users/groups/devices
-- when CSV mappings reference ids that are not present in the snapshot import.

create temporary table tmpmembers (
    usr varchar(20) not null,
    dept varchar(10) not null,
    pi varchar(2),
    unique (usr, dept)
);

create temporary table tmpdev (
    dev varchar(5) not null,
    dept varchar(10) not null,
    unique (dev, dept)
);

create temporary table tmpdpm (
    usr varchar(20) not null,
    dev varchar(5) not null,
    templates varchar(1) not null,
    slot varchar(1) not null,
    technologist varchar(1) not null,
    medical varchar(1) not null,
    training varchar(1) not null,
    unique (usr, dev)
);

\copy tmpmembers(usr, dept, pi) from 'user-dept.csv' with delimiter ',' csv header;
\copy tmpdev(dev, dept) from 'dev-dept.csv' with delimiter ',' csv header;
\copy tmpdpm(usr, dev, templates, slot, technologist, medical, training) from 'devperm.csv' with delimiter ',' csv header;

-- Normalize whitespace and token casing to make validation deterministic.
update tmpmembers
set
    usr = trim(usr),
    dept = trim(dept),
    pi = nullif(lower(trim(coalesce(pi, ''))), '');

update tmpdev
set
    dev = trim(dev),
    dept = trim(dept);

update tmpdpm
set
    usr = trim(usr),
    dev = trim(dev),
    templates = lower(trim(templates)),
    slot = lower(trim(slot)),
    technologist = lower(trim(technologist)),
    medical = lower(trim(medical)),
    training = lower(trim(training));

-- Remove blank rows that can appear in hand-edited CSV files.
delete from tmpmembers where usr = '' or dept = '';
delete from tmpdev where dev = '' or dept = '';
delete from tmpdpm where usr = '' or dev = '';

-- Ensure every devperm user is part of DEV membership set.
insert into tmpmembers (usr, dept, pi)
select distinct d.usr, 'DEV', null
from tmpdpm d
where not exists (
    select 1
    from tmpmembers m
    where m.usr = d.usr and m.dept = 'DEV'
);

do $$
declare
    invalid_pi_count integer;
    invalid_perm_count integer;
    no_permission_count integer;
    multi_pi_group_count integer;
begin
    select count(*)
    into invalid_pi_count
    from tmpmembers
    where pi is not null and pi <> 'pi';

    if invalid_pi_count > 0 then
        raise exception
            'Invalid pi marker(s) in user-dept.csv (expected blank or ''pi''): % row(s)',
            invalid_pi_count;
    end if;

    select count(*)
    into invalid_perm_count
    from tmpdpm
    where templates not in ('y', 'n')
        or slot not in ('y', 'n')
        or technologist not in ('y', 'n')
        or medical not in ('y', 'n')
        or training not in ('y', 'n');

    if invalid_perm_count > 0 then
        raise exception
            'Invalid y/n permission token(s) in devperm.csv: % row(s)',
            invalid_perm_count;
    end if;

    select count(*)
    into no_permission_count
    from tmpdpm
    where templates = 'n'
        and slot = 'n'
        and technologist = 'n'
        and medical = 'n'
        and training = 'n';

    if no_permission_count > 0 then
        raise exception
            'devperm.csv row(s) grant no permissions, violating userdevice constraints: % row(s)',
            no_permission_count;
    end if;

    select count(*)
    into multi_pi_group_count
    from (
        select dept
        from tmpmembers
        where pi = 'pi'
        group by dept
        having count(*) > 1
    ) dup;

    if multi_pi_group_count > 0 then
        raise exception
            'user-dept.csv defines multiple PI rows for at least one group: % group(s)',
            multi_pi_group_count;
    end if;
end
$$;

-- Create required auth principals/devices/groups when CSV mappings
-- reference keys not present in the snapshot import.
create temporary table new_devices (dev varchar(5) primary key);
create temporary table new_users (usr varchar(20) primary key);
create temporary table new_groups (dept varchar(10) primary key);

insert into new_devices (dev)
select distinct x.dev
from (
    select dev from tmpdev
    union all
    select dev from tmpdpm
) x
where not exists (
    select 1 from tlkpscanner s where s.scannercode = x.dev
);

insert into new_users (usr)
select distinct m.usr
from tmpmembers m
where not exists (
    select 1 from tlkpresearcher r where r.researchercode = m.usr
);

insert into new_groups (dept)
select distinct x.dept
from (
    select dept from tmpmembers
    union all
    select dept from tmpdev
) x
where not exists (
    select 1 from tlkpdept d where d.deptcode = x.dept
);

select usr as "Users that will be created" from new_users order by 1;
select dept as "Groups that will be created" from new_groups order by 1;
select dev as "Devices that will be created" from new_devices order by 1;

insert into tlkpresearcher (researchercode)
select usr from new_users;

insert into tlkpdept (deptcode, dept, dept_short, color)
select dept, dept, dept, '#000000' from new_groups;

insert into tlkpscanner (scannercode, scanner)
select dev, dev from new_devices;

insert into groupmembers (deptcode, researchercode, approved)
select m.dept, m.usr, current_timestamp
from tmpmembers m
on conflict (deptcode, researchercode) do update
set approved = coalesce(groupmembers.approved, excluded.approved);

insert into primarygroupmember (deptcode, researchercode)
select m.dept, m.usr
from tmpmembers m
where m.pi = 'pi'
on conflict (deptcode) do update
set researchercode = excluded.researchercode;

insert into devicegroup (scannercode, deptcode)
select d.dev, d.dept
from tmpdev d
on conflict (scannercode, deptcode) do nothing;

insert into userdevice (
    researchercode,
    scannercode,
    templates,
    slot,
    tech,
    medical,
    training
)
select
    d.usr,
    d.dev,
    d.templates = 'y',
    d.slot = 'y',
    d.technologist = 'y',
    d.medical = 'y',
    d.training = 'y'
from tmpdpm d
on conflict (researchercode, scannercode) do update
set
    templates = excluded.templates,
    slot = excluded.slot,
    tech = excluded.tech,
    medical = excluded.medical,
    training = excluded.training;

-- Keep the historical visibility report for operators.
select deptcode as "Groups without PI after mapping import"
from tlkpdept d
where d.department
    and d.iscurrent
    and exists (
        select 1 from groupmembers gm where gm.deptcode = d.deptcode
    )
    and not exists (
        select 1 from primarygroupmember p where p.deptcode = d.deptcode
    )
order by 1;

commit;
