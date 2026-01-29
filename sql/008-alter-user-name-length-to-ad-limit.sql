-- these columns contain AD usernames but are maxlength 15 and the maxlength of AD names is 20

begin;

alter table tblsched alter column researchercode type varchar(20);
alter table tbltemplate alter column researchercode type varchar(20);
alter table tlkpresearcher alter column researchercode type varchar(20);
alter table tlogsched alter column researchercode type varchar(20);
alter table tlogsched alter column researchercode_old type varchar(20);

commit;
