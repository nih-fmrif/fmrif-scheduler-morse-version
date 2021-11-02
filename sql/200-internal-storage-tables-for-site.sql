-- this table is used by the flask session extension
create table site_sessions (
	id serial primary key,
	session_id varchar(255) unique,
	data bytea,
	expiry timestamp without time zone
);
comment on table site_sessions is 'an internal session store for the website, ignore';