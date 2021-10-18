create table groupmembers (
	deptcode varchar(10) not null,
	researchercode varchar(20) not null,
	approve1 timestamp with time zone,
	approve2 timestamp with time zone,
	approved boolean not null generated always as (approve1 is not null and approve2 is not null) stored,
	constraint groupmembers_deptcode_fkey foreign key (deptcode) references tlkpdept on update cascade on delete restrict,
	constraint groupmembers_researchercode_fkey foreign key (researchercode) references tlkpresearcher on update cascade on delete restrict,
	primary key (deptcode, researchercode)
);

comment on table groupmembers is 'group ↔ user';
comment on column groupmembers.deptcode is 'first half of primary key';
comment on column groupmembers.researchercode is 'second half of primary key';
comment on column groupmembers.approve1 is 'approval to join (type 1)';
comment on column groupmembers.approve2 is 'approval to join (type 2)';
comment on column groupmembers.approved is 'true if approved member of group';

create table primarygroupmember (
	deptcode varchar(10) not null,
	researchercode varchar(20) not null,
	constraint primarygroupmember_deptcode_fkey foreign key (deptcode) references tlkpdept on update cascade on delete restrict,
	constraint primarygroupmember_researchercode_fkey foreign key (researchercode) references tlkpresearcher on update cascade on delete restrict,
	constraint primarygroupmember_groupmembers_fkey foreign key (deptcode, researchercode) references groupmembers(deptcode, researchercode) on delete restrict,
	primary key (deptcode, researchercode)
);

comment on table primarygroupmember is 'primary investigator of group';
comment on column primarygroupmember.deptcode is 'first half of primary key';
comment on column primarygroupmember.researchercode is 'second half of primary key';