begin;

-- this is redundant with the primary key
alter table tlkpinst drop column instshort;

-- make it easier to add institutes manually;
alter table tlkpinst alter column inst set default '';

-- in order to maintain referential integrity and allow institutes to be removed
-- we need a mechanism to disable institutes without deleting them
alter table tlkpinst add column hidden boolean not null default false;

-- since these are managed manually set up a nice soft delete system
-- in case of accidents
create function soft_del_inst() returns trigger as $$
declare
	upd text := 'update tlkpinst set hidden = true where instcode = $1';
begin
	execute upd using old.instcode;
	return null;
end;
$$ language plpgsql;
comment on function soft_del_inst is 'implementation of delete_inst trigger';

create trigger delete_inst before delete on tlkpinst for each row execute procedure soft_del_inst();

comment on trigger delete_inst on tlkpinst is 'make deletes on tlkpinst set hidden = true instead';

-- tlkpdept has mix of '' and null for inst, settle on null so this can be a key
update tlkpdept set inst = null where inst = '';

alter table tblsched add constraint tblsched_instcode_fkey foreign key (orig_instcode) references tlkpinst(instcode) on update cascade on delete restrict;

alter table tlkpdept add constraint tlkpdept_inst_fkey foreign key (inst) references tlkpinst(instcode) on update cascade on delete restrict;

alter table tblsched add constraint tblsched_orig_inst_fkey foreign key (orig_instcode) references tlkpinst(instcode) on update cascade on delete restrict;

-- this can now be added back as a valid constraint.
alter table tbltemplate drop constraint tbltemplate_instcode_fkey;
alter table tbltemplate add constraint tbltemplate_instcode_fkey foreign key (instcode) references tlkpinst(instcode) on update cascade on delete restrict;

commit;