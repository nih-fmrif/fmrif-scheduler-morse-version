create table oauth_state (
    state varchar(128) primary key,
    nonce varchar(128) not null,
    redirect_next text,
    created_at timestamp with time zone not null default current_timestamp
);
comment on table oauth_state is 'temporary OAuth state store for server-side login flow';
