create table notification_incident (
	issue_key text primary key,
	issue_type text not null,
	category text not null,
	severity varchar(16) not null,
	title text not null,
	detail text not null,
	href text null,
	link_label text not null default '',
	active boolean not null default true,
	state varchar(16) not null default 'open',
	state_note text not null default '',
	state_changed_by varchar(20) null,
	state_changed_at timestamp with time zone not null default now(),
	ignored_until timestamp with time zone null,
	first_seen_at timestamp with time zone not null default now(),
	last_seen_at timestamp with time zone not null default now(),
	last_detected_at timestamp with time zone null,
	last_resolved_at timestamp with time zone null,
	occurrence_count integer not null default 1,
	fingerprint text not null default ''
);

alter table notification_incident
	add constraint notification_incident_valid_state
	check (state in ('open', 'ignored', 'resolved'));

alter table notification_incident
	add constraint notification_incident_valid_severity
	check (severity in ('warning', 'critical'));

alter table notification_incident
	add constraint notification_incident_occurrence_count_min
	check (occurrence_count >= 1);

create index notification_incident_state_active_idx
	on notification_incident (state, active);

create index notification_incident_category_idx
	on notification_incident (category);

create index notification_incident_last_seen_idx
	on notification_incident (last_seen_at desc);

create index notification_incident_issue_type_idx
	on notification_incident (issue_type);

create index notification_incident_ignored_until_idx
	on notification_incident (ignored_until);

comment on table notification_incident is 'Current detector-driven notification incidents for /app/issues triage.';
comment on column notification_incident.issue_key is 'Stable incident key derived from detector type and entity ids.';
comment on column notification_incident.state is 'Admin/workflow state: open, ignored, or auto-resolved.';
comment on column notification_incident.active is 'True when the latest detector run still observes the issue.';
comment on column notification_incident.ignored_until is 'Optional ignore expiry; null means ignore indefinitely while issue stays active.';
