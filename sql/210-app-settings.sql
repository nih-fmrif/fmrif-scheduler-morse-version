-- Add runtime-editable settings table used by admin panel configuration overrides.
create table if not exists app_settings (
    "key" varchar(128) not null primary key,
    value text not null default '',
    updated_at timestamptz not null default now(),
    updated_by varchar(20)
);
