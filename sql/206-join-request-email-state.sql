alter table groupmembers
    add column email_status varchar(10);

update groupmembers
set email_status = 'none'
where email_status is null;

alter table groupmembers
    alter column email_status set default 'none';

alter table groupmembers
    alter column email_status set not null;

alter table groupmembers
    add constraint groupmembers_valid_email_status
    check (email_status in ('none', 'sent', 'failed'));

comment on column groupmembers.email_status is 'notification state for pending join request: none, sent, failed';

alter table technologist
    add column applied_on timestamp with time zone;

update technologist
set applied_on = approved_on
where applied_on is null;

alter table technologist
    alter column applied_on set default current_timestamp;

alter table technologist
    alter column applied_on set not null;

alter table technologist
    alter column approved_on drop default;

alter table technologist
    alter column approved_on drop not null;

alter table technologist
    add column email_status varchar(10);

update technologist
set email_status = 'none'
where email_status is null;

alter table technologist
    alter column email_status set default 'none';

alter table technologist
    alter column email_status set not null;

alter table technologist
    add constraint technologist_valid_email_status
    check (email_status in ('none', 'sent', 'failed'));

comment on column technologist.applied_on is 'the date the user submitted the technologist join form';
comment on column technologist.approved_on is 'NULL if pending, timestamp of approval date otherwise';
comment on column technologist.email_status is 'notification state for pending technologist request: none, sent, failed';

create or replace view membership as select
    M.deptcode "group",
    M.researchercode "user",
    case when P.deptcode is not null then true else false end as pi,
    M.approved is not null as approved,
    D.iscurrent group_active,
    R.active user_active,
    M.email_status as email_status
from groupmembers M
inner join tlkpdept D using(deptcode)
inner join tlkpresearcher R using(researchercode)
left join primarygroupmember P using(deptcode, researchercode)
order by 1, 3 desc, 2;

comment on column membership.email_status is 'notification state for pending membership request: none, sent, failed';
