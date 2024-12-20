-- Add initial institutes with required fields
INSERT INTO tlkpinst (instcode, instshort, inst) VALUES 
('MAINT', 'MAINT', 'Maintenance'),
('TEST', 'TEST', 'Test Institute'),
('TRAIN', 'TRAIN', 'Training');

-- Add departments with all required fields
INSERT INTO tlkpdept (deptcode, dept, dept_short, grp, color_wkday_day, ismain, iscurrent) VALUES 
('TEST', 'Test Department', 'Test', 'TEST', '000000', true, true),
('DEV', 'Development', 'DEV', 'DEV', '000000', true, true),
('admin', 'Administration', 'admin', 'ADMIN', '000000', true, true);

-- Add test researchers
INSERT INTO tlkpresearcher (researchercode, lname, fname, researchershort, chg_at, active) VALUES
('testuser', 'User', 'Test', 'testuser', CURRENT_TIMESTAMP, true),
('testuser1', 'User1', 'Test1', 'testuser1', CURRENT_TIMESTAMP, true);

-- Add test scanner
INSERT INTO tlkpscanner (scannercode, scanner, descrip, mailinglist, active) VALUES
('TEST', 'Test Scanner', 'Test Scanner Description', 'test@example.com', true);