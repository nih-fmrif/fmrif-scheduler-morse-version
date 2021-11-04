-- this table is used by the flask session extension
create table site_sessions (
	id serial primary key,
	session_id varchar(255) unique,
	data bytea,
	expiry timestamp without time zone
);
comment on table site_sessions is 'an internal session store for the website, ignore';

create table reset_tokens (
	token text not null primary key,
	for_user varchar(20) not null references tlkpresearcher(researchercode) on update cascade on delete cascade,
	issued timestamp with time zone not null default current_timestamp
);
comment on table reset_tokens is 'an internal store for the website, ignore';