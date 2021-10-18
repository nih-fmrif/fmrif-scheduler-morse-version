comment on column tblsched.schedid is 'primary key';
comment on column tblsched.scannercode is 'reference to tlkpscanner';
comment on column tblsched.scheddate is 'civil date of assignment';
comment on column tblsched.scheddow is 'day of the week of assignment (0 = Sunday)';
comment on column tblsched.schedhour is '0-indexed 24 hour civil time of assignment';
comment on column tblsched.deptcode is 'optional reference to tlkpdept currently assigned';
comment on column tblsched.researchercode is 'optional reference to tlkpresearcher currently assigned';
comment on column tblsched.chg_at is 'timestamp of last modification';
comment on column tblsched.chg_by is 'description of last entity to change this row';
comment on column tblsched.templateid is 'reference to tbltemplate that created this row (optional for historical reasons)';
comment on column tblsched.orig_deptcode is 'optional reference to tlkpresearcher originally assigned';
comment on column tblsched.orig_instcode is 'optional reference to tlkpinst originally assigned';

comment on column tbltemplate.templateid is 'primary key';
comment on column tbltemplate.scannercode is 'reference to tlkpscanner';
comment on column tbltemplate.dow is 'day of the week (0 = Sunday) of assignment';
comment on column tbltemplate.hour is '0-indexed 24 hour civil time of assignment';
comment on column tbltemplate.deptcode is 'optional reference to tlkpdept assigned';
comment on column tbltemplate.researchercode is 'optional reference to tlkpresearcher assigned';
comment on column tbltemplate.templatecode is 'with scannercode, references tbltemplates';
comment on column tbltemplate.instcode is 'optional reference to tlkpinst assigned';

comment on column tbltemplates.templatecode is 'unique half of primary key';
comment on column tbltemplates.scannercode is 'reference to tlkpscanner and other half of primary key';
comment on column tbltemplates.template is 'human readable name of template';
comment on column tbltemplates.comments is 'human readable notes about template';
comment on column tbltemplates.hidden is 'if hidden, the template is no longer available to create schedules';

comment on column tlkpdept.deptcode is 'primary key';
comment on column tlkpdept.dept is 'human readable name of department (long)';
comment on column tlkpdept.dept_short is 'human readable name of department (short)';
comment on column tlkpdept.inst is 'optional reference to tlkpinst';
comment on column tlkpdept.email is 'contact address for department';

comment on table tlkpinst is 'List of institutes';
comment on column tlkpinst.instcode is 'primary key';
comment on column tlkpinst.inst is 'human readable name of institute';
comment on column tlkpinst.hidden is 'if hidden, the institute is no longer available for selection';

comment on column tlkpresearcher.researchercode is 'primary key';
comment on column tlkpresearcher.chg_at is 'timestamp of last modification';
comment on column tlkpresearcher.active is 'if not active, no longer be an option anywhere until marked active again';

comment on table tlkpscanner is 'List of devices';
comment on column tlkpscanner.scannercode is 'primary key';
comment on column tlkpscanner.scanner is 'human readable label of device';
comment on column tlkpscanner.descrip is 'description of device';
comment on column tlkpscanner.mailinglist is 'contact address for device';
comment on column tlkpscanner.active is 'if not active, no long an option anywhere';

comment on column tlogsched.logid is 'primary key';
comment on column tlogsched.schedid is 'schedid for logged value, new entries always reference a row in tblsched';
comment on column tlogsched.scannercode is 'value of tblsched.scannercode';
comment on column tlogsched.scheddate is 'value of tblsched.scheddate';
comment on column tlogsched.schedhour is 'value of tblsched.schedhour';
comment on column tlogsched.deptcode is 'value of tblsched.deptcode';
comment on column tlogsched.researchercode is 'value of tblsched.researchercode';
comment on column tlogsched.time_used is 'value of tblsched.time_used';
comment on column tlogsched.scannercode_old is 'previous value of tblsched.scannercode';
comment on column tlogsched.scheddate_old is 'previous value of tblsched.scheddate';
comment on column tlogsched.schedhour_old is 'previous value of tblsched.schedhour';
comment on column tlogsched.deptcode_old is 'previous value of tblsched.deptcode';
comment on column tlogsched.researchercode_old is 'previous value of tblsched.researchercode';
comment on column tlogsched.time_used_old is 'previous value of tblsched.time_used';
comment on column tlogsched.chg_at is 'value of tblsched.chg_at';
comment on column tlogsched.chg_by is 'value of tblsched.chg_by';