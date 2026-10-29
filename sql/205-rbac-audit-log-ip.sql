alter table if exists rbac_audit_log
	add column if not exists ip_addr varchar(64) null;

create index if not exists rbac_audit_log_ip_idx
	on rbac_audit_log (ip_addr);

comment on column rbac_audit_log.ip_addr is 'Source client IP captured at mutation time.';
