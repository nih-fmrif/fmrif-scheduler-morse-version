comment on table tlkpdept is 'List of groups';

-- retrofit ismain column to denote groups with membership
comment on column tlkpdept.ismain is 'true for groups with membership';

-- add new flags (dev is implicit for deptcode = 'DEV')

alter table tlkpdept add column joinable boolean not null default true;
comment on column tlkpdept.joinable is 'true for groups that users may join';

alter table tlkpdept add column archivable boolean not null default true;
comment on column tlkpdept.archivable is 'true for user created groups that may be archived';

alter table tlkpdept add column scheduleable boolean not null default true;
comment on column tlkpdept.scheduleable is 'true for groups that may be referenced in tblsched';

alter table tlkpdept add column department boolean not null generated always as (ismain and archivable and scheduleable) stored;
comment on column tlkpdept.department is 'true for department and false for a special group';

-- update flags for existing special groups

update tlkpdept set (ismain, archivable) = (false, false) where deptcode in (
	'',
	'GE',
	'SIEM',
	'post',
	'test',
	'training'
);

update tlkpdept set (archivable, scheduleable) = (false, false) where deptcode = 'DEV';

update tlkpdept set joinable = false where deptcode in (
	'',
	'GE',
	'SIEM',
	'post',
	'test'
);

update tlkpdept set iscurrent = false where deptcode in (
	'',
	'post',
	'GE',
	'SIEM'
);

-- -- add a training institute to allow resource tracking
-- insert into tlkpinst (instcode, inst) values ('TRAIN', 'Training');
-- update tlkpdept set (inst, joinable) = ('TRAIN', false) where deptcode = 'training';

-- -- add admin and the new maintenance group

-- insert into tlkpdept (deptcode, dept, dept_short, ismain, inst, color, joinable, archivable, scheduleable) values
-- 	('admin', 'admin', 'admin', true, null, '#000000', false, false, false),
-- 	('maint', 'maintenance', 'maint', false, 'MAINT', '#000000', false, false, true);

	-- Add TRAIN institute if not exists
INSERT INTO tlkpinst (instcode, inst) 
SELECT 'TRAIN', 'Training'
WHERE NOT EXISTS (SELECT 1 FROM tlkpinst WHERE instcode = 'TRAIN');

-- Add admin and maint groups if not exist
INSERT INTO tlkpdept (deptcode, dept, dept_short, ismain, inst, color, joinable, archivable, scheduleable)
SELECT t.* FROM (VALUES
    ('admin', 'admin', 'admin', true, null, '#000000', false, false, false),
    ('maint', 'maintenance', 'maint', false, 'MAINT', '#000000', false, false, true)
) AS t(deptcode, dept, dept_short, ismain, inst, color, joinable, archivable, scheduleable)
WHERE NOT EXISTS (SELECT 1 FROM tlkpdept WHERE deptcode = t.deptcode);
