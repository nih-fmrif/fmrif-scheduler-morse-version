create table csp_violation_event (
    eventid bigserial primary key,
    occurred_at timestamptz not null default now(),
    report_type varchar(32) not null default 'csp-report',
    actor varchar(20) not null default 'anonymous',
    ip_addr varchar(64) null,
    user_agent text not null default '',
    document_uri text not null default '',
    referrer text null,
    blocked_uri text null,
    violated_directive text not null default '',
    effective_directive text null,
    original_policy text null,
    source_file text null,
    line_number integer null,
    column_number integer null,
    disposition varchar(16) not null default 'enforce',
    status_code integer null,
    script_sample text null,
    report_body jsonb not null default '{}'::jsonb
);

create index csp_violation_event_occurred_at_idx
    on csp_violation_event (occurred_at desc);

create index csp_violation_event_violated_directive_idx
    on csp_violation_event (violated_directive);

create index csp_violation_event_disposition_idx
    on csp_violation_event (disposition);

comment on table csp_violation_event is 'Recent CSP violation reports received from browsers for admin review.';
comment on column csp_violation_event.report_type is 'Legacy csp-report payloads and Reporting API csp-violation payloads are both supported.';
comment on column csp_violation_event.document_uri is 'Document URL the browser reported when the violation occurred.';
comment on column csp_violation_event.report_body is 'Sanitized raw CSP report body stored for troubleshooting in the admin panel.';
