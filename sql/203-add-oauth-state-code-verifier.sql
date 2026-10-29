alter table oauth_state add column if not exists code_verifier varchar(128);
