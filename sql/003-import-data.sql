-- Compact synthetic seed for development/test bootstrap.
--
-- This file intentionally encodes a small but behavior-rich dataset that keeps
-- legacy SQL migrations and route tests representative without historical volume.

-- Institutes
INSERT INTO tlkpinst (instcode, instshort, inst) VALUES
('MAINT', 'MAINT', 'Maintenance'),
('TEST', 'TEST', 'Test Institute'),
('TRAIN', 'TRAIN', 'Training Institute');

-- Groups
INSERT INTO tlkpdept (
    deptcode,
    dept,
    dept_short,
    grp,
    color_wkday_day,
    color_wkday_eve,
    color_wkend_day,
    color_wkend_eve,
    ismain,
    iscurrent,
    inst,
    prog,
    link,
    pi,
    lose_to,
    email
) VALUES
('DEV', 'Development', 'DEV', 'DEV', '222222', NULL, NULL, NULL, true, true, 'TEST', '', '', '', NULL, ''),
('TEST', 'Test Department', 'Test', 'TEST', '003366', NULL, NULL, NULL, true, true, 'TEST', '', '', '', NULL, ''),
('admin', 'Administration', 'admin', 'ADMIN', '000000', NULL, NULL, NULL, true, true, 'MAINT', '', '', '', NULL, ''),
('OLD', 'Archived Group', 'Old', 'OLD', '666666', NULL, NULL, NULL, true, false, 'MAINT', '', '', '', NULL, '');

-- Users
INSERT INTO tlkpresearcher (
    researchercode,
    lname,
    fname,
    dept_code,
    researchershort,
    chg_at,
    chg_by,
    lose_to
) VALUES
('testuser', 'User', 'Test', 'TEST', 'testuser', CURRENT_TIMESTAMP, 'seed', NULL),
('testuser1', 'User1', 'Test1', 'DEV', 'testuser1', CURRENT_TIMESTAMP, 'seed', NULL),
('devpi', 'Pi', 'Dev', 'DEV', 'devpi', CURRENT_TIMESTAMP, 'seed', NULL),
('techuser', 'Tech', 'User', 'DEV', 'techuser', CURRENT_TIMESTAMP, 'seed', NULL);

-- Devices
INSERT INTO tlkpscanner (scannercode, scanner, descrip, mailinglist, active) VALUES
('TEST', 'Test Scanner', 'Primary test scanner', 'test@example.com', true),
('LAB1', 'Lab Scanner 1', 'Secondary scanner', 'lab1@example.com', true),
('OLD1', 'Old Scanner', 'Inactive scanner', 'old1@example.com', false);

-- Templates (include active and hidden variants)
INSERT INTO tbltemplates (templatecode, scannercode, template, comments, hidden) VALUES
('A', 'TEST', 'Default', 'Main template', false),
('B', 'TEST', 'Evening', 'Evening template', true),
('A', 'LAB1', 'Lab1 Default', '', false);

-- Template entries
INSERT INTO tbltemplate (
    templateid,
    scannercode,
    dow,
    hour,
    deptcode,
    researchercode,
    templatecode,
    instcode
) VALUES
(1001, 'TEST', 1, 9, 'TEST', 'testuser', 'A', 'TEST'),
(1002, 'TEST', 1, 10, 'DEV', NULL, 'A', 'TEST'),
(1003, 'TEST', 2, 11, 'DEV', 'devpi', 'A', 'TRAIN'),
(1004, 'TEST', 3, 19, 'DEV', 'techuser', 'B', 'TRAIN'),
(1005, 'LAB1', 1, 9, 'TEST', NULL, 'A', NULL);

-- Schedule rows (cover used true/false/null and nullable assignment columns)
INSERT INTO tblsched (
    schedid,
    scannercode,
    scheddate,
    scheddow,
    schedhour,
    deptcode,
    researchercode,
    time_used,
    chg_at,
    chg_by,
    billdeptcode,
    templateid,
    post_on,
    orig_deptcode,
    orig_instcode
) VALUES
(2001, 'TEST', DATE '2026-01-05', 1, 9, 'TEST', 'testuser', true, CURRENT_TIMESTAMP, 'seed', 'TEST', 1001, NULL, 'TEST', 'TEST'),
(2002, 'TEST', DATE '2026-01-05', 1, 10, 'DEV', NULL, NULL, CURRENT_TIMESTAMP, 'seed', 'DEV', 1002, NULL, 'DEV', 'TEST'),
(2003, 'TEST', DATE '2026-01-05', 1, 11, 'DEV', 'devpi', false, CURRENT_TIMESTAMP, 'seed', 'DEV', 1003, NULL, 'DEV', 'TRAIN'),
(2004, 'LAB1', DATE '2026-01-06', 2, 9, 'TEST', NULL, NULL, CURRENT_TIMESTAMP, 'seed', NULL, NULL, NULL, NULL, NULL);

-- Historical schedule log entries backing /json/v1/log/<id>
INSERT INTO tlogsched (
    logid,
    schedid,
    scannercode,
    scheddate,
    schedhour,
    deptcode,
    researchercode,
    time_used,
    scannercode_old,
    scheddate_old,
    schedhour_old,
    deptcode_old,
    researchercode_old,
    time_used_old,
    chg_at,
    chg_by
) VALUES
(3001, 2001, 'TEST', DATE '2026-01-05', 9, 'TEST', 'testuser', true, NULL, NULL, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP - INTERVAL '2 hours', 'seed'),
(3002, 2001, 'TEST', DATE '2026-01-05', 9, 'TEST', 'testuser1', true, 'TEST', DATE '2026-01-05', 9, 'TEST', 'testuser', true, CURRENT_TIMESTAMP - INTERVAL '1 hours', 'seed'),
(3003, 2003, 'TEST', DATE '2026-01-05', 11, 'DEV', 'devpi', false, 'TEST', DATE '2026-01-05', 11, 'DEV', NULL, NULL, CURRENT_TIMESTAMP, 'seed');

-- Legacy/deprecated table still present in historical schema
INSERT INTO technicalscans (
    subject,
    scantime,
    scannercode,
    deptcode,
    comments,
    fullname
) VALUES
('SYN001', CURRENT_TIMESTAMP, 'TEST', 'TEST', 'synthetic sample', 'Synthetic Subject');

-- Keep sequence heads above seeded ids.
SELECT pg_catalog.setval('tblsched_schedid_seq', 2004, true);
SELECT pg_catalog.setval('tbltemplate_templateid_seq', 1005, true);
SELECT pg_catalog.setval(pg_catalog.pg_get_serial_sequence('technicalscans', 'tsid'), 1, true);
SELECT pg_catalog.setval(pg_catalog.pg_get_serial_sequence('tlogresearcher', 'logid'), 1, true);
SELECT pg_catalog.setval(pg_catalog.pg_get_serial_sequence('tlogsched', 'logid'), 3003, true);
