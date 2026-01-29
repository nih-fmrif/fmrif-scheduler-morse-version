-- add back constraints after import (take on "not valid" to prevent old rows from causing errors)

ALTER TABLE ONLY tblsched
    ADD CONSTRAINT tblsched_billdeptcode_fkey FOREIGN KEY (billdeptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE not valid;

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE not valid;

ALTER TABLE ONLY tbltemplates
    ADD CONSTRAINT tbltemplates_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES tlkpscanner(scannercode) ON UPDATE CASCADE DEFERRABLE not valid;

ALTER TABLE ONLY tblsched
    ADD CONSTRAINT tblsched_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE not valid;

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_scannercode_fkey FOREIGN KEY (scannercode, templatecode) REFERENCES tbltemplates(scannercode, templatecode) ON UPDATE CASCADE DEFERRABLE not valid;

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_instcode_fkey FOREIGN KEY (instcode) REFERENCES tlkpinst(instcode) not valid;
