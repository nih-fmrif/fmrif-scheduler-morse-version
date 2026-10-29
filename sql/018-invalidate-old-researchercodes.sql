-- ensure there are no collision with AD names and old researchercodes.
-- the old length limit on researchercode names ensures this is safe
-- and the [] make this an invalid AD login name
--
-- This must be idempotent because the current bootstrap supports both:
-- - pre-018 seed dumps (researchercode without [OLD])
-- - post-018 seed dumps taken from an old production database
update tlkpresearcher
set researchercode = researchercode || '[OLD]'
where researchercode not like '%[OLD]';
