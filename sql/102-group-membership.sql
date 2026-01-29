create table groupmembers (
	deptcode varchar(10) not null,
	researchercode varchar(20) not null,
	approved timestamp with time zone,
	constraint groupmembers_deptcode_fkey foreign key (deptcode) references tlkpdept on update cascade on delete restrict,
	constraint groupmembers_researchercode_fkey foreign key (researchercode) references tlkpresearcher on update cascade on delete restrict,
	primary key (deptcode, researchercode)
);

comment on table groupmembers is 'group ↔ user';
comment on column groupmembers.deptcode is 'first half of primary key';
comment on column groupmembers.researchercode is 'second half of primary key';
comment on column groupmembers.approved is 'NULL if pending, timestamp of approval date otherwise';

create table primarygroupmember (
	deptcode varchar(10) primary key,
	researchercode varchar(20) not null,
	constraint primarygroupmember_deptcode_fkey foreign key (deptcode) references tlkpdept on update cascade on delete restrict,
	constraint primarygroupmember_researchercode_fkey foreign key (researchercode) references tlkpresearcher on update cascade on delete restrict,
	constraint primarygroupmember_groupmembers_fkey foreign key (deptcode, researchercode) references groupmembers(deptcode, researchercode) on delete restrict
);

comment on table primarygroupmember is 'primary investigator of group';
comment on column primarygroupmember.deptcode is 'first half of primary key';
comment on column primarygroupmember.researchercode is 'second half of primary key';

create table technologist (
	researchercode varchar(20) primary key references tlkpresearcher on update cascade on delete restrict,
	approved_on timestamp with time zone not null default current_timestamp
);

comment on table technologist is'users who may answer technologist support requests on a device';
comment on column technologist.researchercode is 'the user in question';
comment on column technologist.approved_on is 'the date the user submitted the technologist join form';
