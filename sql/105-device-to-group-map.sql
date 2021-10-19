create table devicegroup (
	scannercode varchar(5),
	deptcode varchar(10),
	constraint groupdevice_scannercode_fkey foreign key (scannercode) references tlkpscanner(scannercode) on update cascade on delete restrict,
	constraint groupdevice_deptcode_fkey foreign key (deptcode) references tlkpdept(deptcode) on update cascade on delete restrict,
	primary key (scannercode, deptcode)
);

comment on table devicegroup is 'device ↔ group';
comment on column devicegroup.scannercode is 'first half of primary key';
comment on column devicegroup.deptcode is 'second half of primary key';