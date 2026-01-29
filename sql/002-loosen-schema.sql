-- drop constraints that cause import to fail

alter table tblsched drop constraint tblsched_billdeptcode_fkey;

alter table tbltemplate drop constraint tbltemplate_deptcode_fkey;

alter table tbltemplates drop constraint tbltemplates_scannercode_fkey;

-- this will never be added back as the table gets deprecated
alter table technicalscans drop constraint technicalscans_deptcode_fkey;

alter table tblsched drop constraint tblsched_deptcode_fkey;

alter table tbltemplate	drop constraint tbltemplate_scannercode_fkey;

-- this will never be added back as the table gets deprecated
alter table technicalscans drop constraint technicalscans_scannercode_fkey;

alter table tbltemplate drop constraint tbltemplate_instcode_fkey;
