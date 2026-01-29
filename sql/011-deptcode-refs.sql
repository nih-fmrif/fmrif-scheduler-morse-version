begin;

-- billdeptcode is deprecated, do not care about its ref. integrity
alter table tblsched drop constraint tblsched_billdeptcode_fkey;

-- let deptcode be a valid fkey by allowing it to be optional
-- in order to accomodate historical data

alter table tblsched drop constraint tblsched_deptcode_fkey;
alter table tblsched alter column deptcode drop not null;

ALTER TABLE ONLY tblsched
    ADD CONSTRAINT tblsched_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;

-- make orig_deptcode an optional fkey as well


alter table tblsched add constraint tblsched_orig_deptcode_fkey foreign key (orig_deptcode) references tlkpdept(deptcode) on update cascade on delete restrict;


-- we also do this to tbltemplate

alter table tbltemplate alter column deptcode drop not null;
alter table tbltemplate drop constraint tbltemplate_deptcode_fkey;


ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;

commit;
