begin;

create temporary table tmpmembers (
	usr varchar(20) not null,
	dept varchar(10) not null,
	pi varchar(2),
	check(pi is null or pi = 'pi'),
	unique(usr, dept)
);

create temporary table tmpdev (
	dev varchar(5) not null,
	dept varchar(10) not null,
	unique(dev, dept)
);

create temporary table tmpdpm (
	usr varchar(20) not null,
	dev varchar(5) not null,
	templates varchar(1) not null,
	slot varchar(1) not null,
	technologist varchar(1) not null,
	medical varchar(1) not null,
	training varchar(1) not null,
	check(templates in ('y', 'n')),
	check(slot in ('y', 'n')),
	check(technologist in ('y', 'n')),
	check(medical in ('y', 'n')),
	check(training in ('y', 'n')),
	unique(usr, dev)
);

\copy tmpmembers(usr, dept, pi) from 'user-dept.csv' with delimiter ',' csv header;
\copy tmpdev(dev, dept) from 'dev-dept.csv' with delimiter ',' csv header;
\copy tmpdpm(usr, dev, templates, slot, technologist, medical, training) from 'devperm.csv' with delimiter ',' csv header;

-- make sure every user in devperm.csv is in dev group
insert into tmpmembers (usr, dept) select usr, 'DEV' from tmpdpm D where not exists (
	select * from tmpmembers M where M.dept = 'DEV' and M.usr = D.usr
);

-- we need to do some set ops and reference the results multiple times
create temporary table new_devices (dev varchar(5) primary key);
create temporary table new_users (usr varchar(20) primary key);
create temporary table new_departments (dept varchar(10) primary key);

insert into new_devices(dev) select distinct dev from (
	select dev from tmpdev
	union all
	select dev from tmpdpm
	except
	select scannercode dev from tlkpscanner
) t;

-- note all tmpdpm users are in tmpmembers now by construction
insert into new_users(usr) select distinct usr from (
	select usr from tmpmembers 
	except
	select researchercode usr from tlkpresearcher
) t;

insert into new_departments(dept) select distinct dept from (
	select dept from tmpmembers
	union all
	select dept from tmpdev
	except
	select deptcode dept from tlkpdept
) t;

-- list out all the new entities being created to fill in gaps and then create them
select usr as "Users that will be created" from new_users order by 1;
select dept as "Departments that will be created" from new_departments order by 1;
select dev as "Devices that will be created" from new_devices order by 1;
insert into tlkpresearcher(researchercode) select usr from new_users;
insert into tlkpdept(deptcode, dept, dept_short, color) select dept, dept, dept, '#000000' from new_departments;
insert into tlkpscanner(scannercode, scanner) select dev, dev from new_devices;

-- now that we know everything exists properly we can create the real relations
insert into groupmembers(deptcode, researchercode, approve1, approve2) select dept, usr, current_timestamp, current_timestamp from tmpmembers;
insert into primarygroupmember(deptcode, researchercode) select dept, usr from tmpmembers where pi = 'pi';
insert into devicegroup(scannercode, deptcode) select dev, dept from tmpdev; 
insert into userdevice(researchercode, scannercode, templates, slot, tech, medical, training) select
	usr,
	dev,
	templates = 'y',
	slot = 'y',
	technologist = 'y',
	medical = 'y',
	training = 'y'
from tmpdpm;

-- report any still missing info
select deptcode as "Departments without pi" from tlkpdept D where department and iscurrent and not exists (
	select * from primarygroupmember P where P.deptcode = D.deptcode
) order by 1;

commit;