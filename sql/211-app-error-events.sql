create table app_error_event (
    eventid bigserial primary key,
    reference_id varchar(32) not null,
    occurred_at timestamptz not null default now(),
    actor varchar(20) not null,
    ip_addr varchar(64) null,
    user_agent text not null default '',
    method varchar(8) not null,
    where_path text not null,
    endpoint text null,
    status_code integer not null default 500,
    exception_type text not null,
    exception_message text not null,
    fingerprint text not null,
    request_context jsonb not null default '{}'::jsonb,
    stack_trace text not null
);

create unique index app_error_event_reference_id_idx
    on app_error_event (reference_id);

create index app_error_event_occurred_at_idx
    on app_error_event (occurred_at desc);

create index app_error_event_actor_idx
    on app_error_event (actor);

create index app_error_event_exception_type_idx
    on app_error_event (exception_type);

create index app_error_event_fingerprint_idx
    on app_error_event (fingerprint);

create index app_error_event_where_path_idx
    on app_error_event (where_path);

comment on table app_error_event is 'Append-only log of unhandled request exceptions surfaced in the admin panel.';
comment on column app_error_event.reference_id is 'User-facing error reference shown on HTML/JSON 500 responses.';
comment on column app_error_event.request_context is 'Sanitized request, actor, and routing context captured at failure time.';
comment on column app_error_event.fingerprint is 'Grouping key derived from exception type, route, and top application frame.';
