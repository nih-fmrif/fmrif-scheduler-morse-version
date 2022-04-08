-- the '' group is replaced by NULL in the new schema
-- old entries use ''
-- there are too many special cases and semipredicate issues involved with supporting '' for legacy data
-- therefore we rename the locked '' group to something nonempty so that old entries work correctly
-- albeitly more verbosely and often causing what are otherwise hidden hours to be shown
update tlkpdept set (deptcode, dept) = ('(none)', '(unassigned)') where deptcode = '';