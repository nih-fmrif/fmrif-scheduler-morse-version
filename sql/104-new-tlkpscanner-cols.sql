alter table tlkpscanner add column techaddr text not null default '';
comment on column tlkpscanner.techaddr is 'contact address for technologist requests';

alter table tlkpscanner add column medaddr text not null default '';
comment on column tlkpscanner.medaddr is 'contact address for medical coverage requests';

alter table tlkpscanner add column trainaddr text not null default '';
comment on column tlkpscanner.trainaddr is 'contact address for training requests';
