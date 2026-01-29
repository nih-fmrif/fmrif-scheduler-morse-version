begin;
-- many relations have a mix of null and the zero value for missing values
-- where it should be null always use null, where it should be the zero value always use the zero value.
-- document exceptions

-- some columns are left out for processing at later stages

update tblsched set researchercode = null where researchercode = '';

comment on column tblsched.time_used is 'null initially and periodically set to true or false by DICOM sync';

update tbltemplate set researchercode = null where researchercode = '';

alter table tbltemplates alter column template set not null;

update tbltemplates set comments = '' where comments is null;
alter table tbltemplates alter column comments set default '';
alter table tbltemplates alter column comments set not null;

update tbltemplates set hidden = false where hidden is null;
alter table tbltemplates alter column hidden set not null;

update tlkpdept set ismain = false where ismain is null;
alter table tlkpdept alter column ismain set not null;

update tlkpdept set iscurrent = false where iscurrent is null;
alter table tlkpdept alter column iscurrent set not null;

alter table tlkpdept alter column grp set default '';

update tlkpdept set link = '' where link is null;
alter table tlkpdept alter column link set default '';
alter table tlkpdept alter column link set not null;

-- dept.email and scanner.mailing list are length limited for no solid reason
-- use more efficient text type for these.

update tlkpdept set email = '' where email is null;
alter table tlkpdept alter column email type text;
alter table tlkpdept alter column email set default '';
alter table tlkpdept alter column email set not null;

update tlkpdept set prog = '' where prog is null;
alter table tlkpdept alter column prog set default '';
alter table tlkpdept alter column prog set not null;

-- deprecated columns, remove constraint
alter table tlkpresearcher alter column chg_by drop not null;
alter table tlkpresearcher alter column lname drop not null;
alter table tlkpresearcher alter column fname drop not null;
alter table tlkpresearcher alter column researchershort drop not null;

update tlkpscanner set descrip = '' where descrip is null;
alter table tlkpscanner alter column descrip set default '';
alter table tlkpscanner alter column descrip set not null;

update tlkpscanner set mailinglist = '' where mailinglist is null;
alter table tlkpscanner alter column mailinglist type text;
alter table tlkpscanner alter column mailinglist set default '';
alter table tlkpscanner alter column mailinglist set not null;

update tlkpscanner set active = false where active is null;
alter table tlkpscanner alter column active set default true;
alter table tlkpscanner alter column active set not null;

commit;
