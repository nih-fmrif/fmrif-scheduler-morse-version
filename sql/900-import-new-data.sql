begin;

-- Add initial departments if they don't exist
INSERT INTO tlkpdept (deptcode, dept, dept_short, color, ismain, iscurrent) 
SELECT t.* FROM (VALUES
    ('TEST', 'Test Department', 'Test', '#000000', true, true),
    ('DEV', 'Development', 'DEV', '#000000', true, true)
) AS t(deptcode, dept, dept_short, color, ismain, iscurrent)
WHERE NOT EXISTS (
    SELECT 1 FROM tlkpdept WHERE deptcode = t.deptcode
);

-- Add test users if they don't exist
INSERT INTO tlkpresearcher (researchercode, name, email)
SELECT 'testuser', 'Test User', 'testuser@example.com'
WHERE NOT EXISTS (
    SELECT 1 FROM tlkpresearcher WHERE researchercode = 'testuser'
);

-- Add device permissions if they don't exist
INSERT INTO userdevice(researchercode, scannercode, templates, slot, tech, medical, training)
SELECT 'testuser', 'TEST', true, true, false, false, false
WHERE NOT EXISTS (
    SELECT 1 FROM userdevice 
    WHERE researchercode = 'testuser' AND scannercode = 'TEST'
);

-- Add device-department mappings if they don't exist
INSERT INTO devicegroup(scannercode, deptcode)
SELECT t.* FROM (VALUES
    ('TEST', 'TEST'),
    ('TEST', 'DEV')
) AS t(scannercode, deptcode)
WHERE NOT EXISTS (
    SELECT 1 FROM devicegroup 
    WHERE scannercode = t.scannercode AND deptcode = t.deptcode
);

-- Add user-department mappings with PI status if they don't exist
INSERT INTO groupmembers(deptcode, researchercode, approved)
SELECT t.* FROM (VALUES
    ('TEST', 'testuser', CURRENT_TIMESTAMP),
    ('DEV', 'testuser', CURRENT_TIMESTAMP)
) AS t(deptcode, researchercode, approved)
WHERE NOT EXISTS (
    SELECT 1 FROM groupmembers 
    WHERE deptcode = t.deptcode AND researchercode = t.researchercode
);

INSERT INTO primarygroupmember(deptcode, researchercode)
SELECT 'DEV', 'testuser'
WHERE NOT EXISTS (
    SELECT 1 FROM primarygroupmember 
    WHERE deptcode = 'DEV' AND researchercode = 'testuser'
);

commit;
