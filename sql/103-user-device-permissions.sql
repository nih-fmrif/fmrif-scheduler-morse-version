create table userdevice (
	researchercode varchar(20),
	scannercode varchar(5),
	templates bool not null,
	slot bool not null,
	tech bool not null,
	medical bool not null,
	training bool not null,
	constraint userdevice_researchercode_fkey foreign key (researchercode) references tlkpresearcher(researchercode) on update cascade on delete restrict,
	constraint userdevice_scannercode_fkey foreign key (scannercode) references tlkpscanner(scannercode) on update cascade on delete restrict,
	-- ensure at least one permission is selected
	constraint userdevice_at_least_one_permission check (templates or slot or tech or medical or training),
	primary key (researchercode, scannercode)
);

comment on table userdevice is 'user ↔ device dev group permissions';
comment on column userdevice.researchercode is 'first half of primary key';
comment on column userdevice.scannercode is 'second half of primary key';
comment on column userdevice.templates is 'permission to edit and apply templates on this device';
comment on column userdevice.slot is 'permission to edit any slot on this device';
comment on column userdevice.tech is 'permission to respond to requests for technologist on this device';
comment on column userdevice.medical is 'permission to respond to requests for medical coverage on this device';
comment on column userdevice.training is 'permission to respond to requests for training on this device';