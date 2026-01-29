
-- the 't' scanner was active from 2000-01-01 to 2006-12-31
-- but was deleted from the database. Add it back so we can create a valid fkey.
insert into tlkpscanner(scannercode, scanner, active) values ('t', '<DELETED after 2007>', false);

alter table tblsched add constraint tblsched_scanner_fkey foreign key (scannercode) references tlkpscanner(scannercode) on update cascade on delete restrict;


-- this can now be marked as a valid constraint. (And renamed)
alter table tbltemplate	drop constraint tbltemplate_scannercode_fkey;
ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_scanner_and_templatecode_fkey FOREIGN KEY (scannercode, templatecode) REFERENCES tbltemplates(scannercode, templatecode) ON UPDATE CASCADE ON DELETE RESTRICT;


alter table tbltemplate add constraint tbltemplate_scannercode_fkey foreign key (scannercode) references tlkpscanner(scannercode) on update cascade on delete restrict;

-- this can now be marked valid.
alter table tbltemplates drop constraint tbltemplates_scannercode_fkey;
ALTER TABLE ONLY tbltemplates
    ADD CONSTRAINT tbltemplates_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES tlkpscanner(scannercode) ON UPDATE CASCADE ON DELETE RESTRICT;
