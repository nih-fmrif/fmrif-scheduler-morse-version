-- ensure there are no collision with AD names and old researchercodes.
-- the old length limit on researchercode names ensures this is safe
-- and the [] make this an invalid AD login name
update tlkpresearcher set researchercode = researchercode || '[OLD]';
