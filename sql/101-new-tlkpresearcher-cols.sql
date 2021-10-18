comment on table tlkpresearcher is 'List of users';

alter table tlkpresearcher add column name text not null default '';
comment on column tlkpresearcher.name is 'Full name as reported by AD';

-- backfill something similar to SM name
update tlkpresearcher set name = lname || ', ' || fname;

alter table tlkpresearcher add column email text not null default '';
comment on column tlkpresearcher.email is 'email address as reported by AD';