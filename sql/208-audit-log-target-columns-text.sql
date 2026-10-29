alter table if exists rbac_audit_log
	alter column deptcode type text using deptcode::text,
	alter column scannercode type text using scannercode::text,
	alter column researchercode type text using researchercode::text,
	alter column requestercode type text using requestercode::text;

alter table if exists email_audit_log
	alter column deptcode type text using deptcode::text,
	alter column scannercode type text using scannercode::text,
	alter column researchercode type text using researchercode::text,
	alter column requestercode type text using requestercode::text;
