comment on table technicalscans is 'Deprecated';
comment on table tlogresearcher is 'Deprecated';

comment on column tlkpresearcher.lname is 'Deprecated'; -- these two need to be replaced by a new column
comment on column tlkpresearcher.fname is 'Deprecated';

comment on column tlkpresearcher.researchershort is 'Deprecated';
comment on column tlkpresearcher.chg_by is 'Deprecated';
comment on column tlkpresearcher.lose_to is 'Deprecated';
comment on column tlkpresearcher.dept_code is 'Deprecated'; -- no longer explicitly tracked

comment on column tlkpdept.grp is 'Deprecated';
comment on column tlkpdept.prog is 'Deprecated';
comment on column tlkpdept.lose_to is 'Deprecated';
comment on column tlkpdept.pi is 'Deprecated'; -- needs to be replaced with a new column

comment on column tblsched.post_on is 'Deprecated';

-- This may be revivived in the future but is deprecated for now;
comment on column tblsched.billdeptcode is 'Deprecated';
