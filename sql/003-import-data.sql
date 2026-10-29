-- Rooted legacy seed for development/test bootstrap.
--
-- Template and reference data are generated from a bootstrapped old database via
-- scripts/generate-rooted-template-seed.py and imported here in pre-018 form so
-- the current migration chain can recreate rooted legacy markers such as
-- `[OLD]` researcher codes through 018-invalidate-old-researchercodes.sql.
-- The generated artifact emits explicit tbltemplate rows in dump shape because
-- sql/000-init.sh loads this seed under session_replication_role=replica.

\ir generated-rooted-template-subset.sql

-- Current-dated schedule rows for scheduler interaction tests.
-- These stay group-reserved or open so that later auth/group imports from
-- 900-import-new-data.sql can be used to book them with active users.
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
(2001, 'd', DATE '2026-01-05', 1, 9, 'training', NULL, NULL, CURRENT_TIMESTAMP, 'seed', 'training', NULL, NULL, 'training', 'DEV'),
(2002, 'd', DATE '2026-01-05', 1, 10, 'HCPS', NULL, NULL, CURRENT_TIMESTAMP, 'seed', 'HCPS', NULL, NULL, 'HCPS', 'NINDS'),
(2003, 'd', DATE '2026-01-06', 2, 11, 'NCCIH', NULL, NULL, CURRENT_TIMESTAMP, 'seed', 'NCCIH', NULL, NULL, 'NCCIH', 'NCCIH'),
(2004, 'test', DATE '2026-01-05', 1, 9, '(none)', NULL, NULL, CURRENT_TIMESTAMP, 'seed', '(none)', NULL, NULL, '(none)', NULL);

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
(3001, 2001, 'd', DATE '2026-01-05', 9, 'training', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP - INTERVAL '2 hours', 'seed'),
(3002, 2002, 'd', DATE '2026-01-05', 10, 'HCPS', NULL, NULL, 'd', DATE '2026-01-05', 10, NULL, NULL, NULL, CURRENT_TIMESTAMP - INTERVAL '1 hours', 'seed'),
(3003, 2003, 'd', DATE '2026-01-06', 11, 'NCCIH', NULL, NULL, 'd', DATE '2026-01-06', 11, NULL, NULL, NULL, CURRENT_TIMESTAMP, 'seed');

-- Legacy/deprecated table still present in historical schema.
INSERT INTO technicalscans (
    subject,
    scantime,
    scannercode,
    deptcode,
    comments,
    fullname
) VALUES
('ROOTED001', CURRENT_TIMESTAMP, 'd', 'NMRF', 'rooted sample', 'Rooted Subject');

-- Keep sequence heads above seeded ids.
SELECT pg_catalog.setval('tblsched_schedid_seq', 2004, true);
SELECT pg_catalog.setval(
    'tbltemplate_templateid_seq',
    COALESCE((SELECT MAX(templateid) FROM tbltemplate), 1),
    true
);
SELECT pg_catalog.setval(pg_catalog.pg_get_serial_sequence('technicalscans', 'tsid'), 1, true);
SELECT pg_catalog.setval(pg_catalog.pg_get_serial_sequence('tlogresearcher', 'logid'), 1, true);
SELECT pg_catalog.setval(pg_catalog.pg_get_serial_sequence('tlogsched', 'logid'), 3003, true);
