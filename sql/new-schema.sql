--
-- PostgreSQL database dump
--

-- Dumped from database version 13.4 (Debian 13.4-3)
-- Dumped by pg_dump version 13.4 (Debian 13.4-3)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: log_sched_changes_impl(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.log_sched_changes_impl() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
	begin
		if(TG_OP = 'UPDATE') then
			insert into tlogsched (
				schedid,
				scannercode, scheddate, schedhour, deptcode, researchercode, time_used,
				scannercode_old, scheddate_old, schedhour_old, deptcode_old, researchercode_old, time_used_old,
				chg_at, chg_by
			) values (
				NEW.schedid,
				NEW.scannercode, NEW.scheddate, NEW.schedhour, NEW.deptcode, NEW.researchercode, NEW.time_used,
				OLD.scannercode, OLD.scheddate, OLD.schedhour, OLD.deptcode, OLD.researchercode, OLD.time_used,
				NEW.chg_at, NEW.chg_by
			);
			return NEW;
		elseif(TG_OP = 'DELETE') then
			insert into tlogsched (
				schedid,
				scannercode, scheddate, schedhour, -- need these for reference, but leave rest of new values null as they're gone
				scannercode_old, scheddate_old, schedhour_old, deptcode_old, researchercode_old, time_used_old
			) values (
				OLD.schedid,
				OLD.scannercode, OLD.scheddate, OLD.schedhour, -- keep these to relate the entry back
				OLD.scannercode, OLD.scheddate, OLD.schedhour, OLD.deptcode, OLD.researchercode, OLD.time_used
			);
			return OLD;
		elseif(TG_OP = 'INSERT') then
			insert into tlogsched (
				schedid,
				scannercode, scheddate, schedhour, deptcode, researchercode, time_used,
				chg_at, chg_by
			) values (
				NEW.schedid,
				NEW.scannercode, NEW.scheddate, NEW.schedhour, NEW.deptcode, NEW.researchercode, NEW.time_used,
				NEW.chg_at, NEW.chg_by
			);
			return NEW;
		end if;
	end;
$$;


--
-- Name: log_support_impl(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.log_support_impl() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
	begin
		if(TG_OP = 'UPDATE') then
			insert into supportlog (
				schedid, supportkind,
				filed_by, fulfilled_by, approved, note,
				filed_by_old, fulfilled_by_old, approved_old, note_old,
				chg_by, chg_at
			) values (
				NEW.schedid, NEW.supportkind,
				NEW.filed_by, NEW.fulfilled_by, NEW.approved, NEW.note,
				OLD.filed_by, OLD.fulfilled_by, OLD.approved, old.note,
				NEW.chg_by, NEW.chg_at
			);
		elseif(TG_OP = 'INSERT') then
			insert into supportlog (
				schedid, supportkind,
				filed_by, fulfilled_by, approved, note,
				chg_by, chg_at
			) values (
				NEW.schedid, NEW.supportkind,
				NEW.filed_by, NEW.fulfilled_by, NEW.approved, NEW.note,
				NEW.chg_by, NEW.chg_at
			);
		end if;
		return NEW;
	end;
$$;


--
-- Name: soft_del_inst(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.soft_del_inst() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
declare
	upd text := 'update tlkpinst set active = false where instcode = $1';
begin
	execute upd using old.instcode;
	return null;
end;
$_$;


--
-- Name: FUNCTION soft_del_inst(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.soft_del_inst() IS 'implementation of delete_inst trigger';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: supportkind; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supportkind (
    supportkind integer NOT NULL,
    label text NOT NULL
);


--
-- Name: TABLE supportkind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.supportkind IS 'Kind of support request';


--
-- Name: COLUMN supportkind.supportkind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.supportkind.supportkind IS 'primary key';


--
-- Name: COLUMN supportkind.label; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.supportkind.label IS 'human readable label';


--
-- Name: supportlog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supportlog (
    logid bigint NOT NULL,
    schedid integer,
    supportkind integer,
    filed_by character varying(20),
    fulfilled_by character varying(20),
    approved boolean,
    note text NOT NULL,
    filed_by_old character varying(20),
    fulfilled_by_old character varying(20),
    approved_old boolean,
    note_old text DEFAULT ''::text NOT NULL,
    chg_by character varying(20) NOT NULL,
    chg_at timestamp with time zone NOT NULL
);


--
-- Name: TABLE supportlog; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.supportlog IS 'Logged changes from support';


--
-- Name: tlogsched; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tlogsched (
    logid integer NOT NULL,
    schedid integer,
    scannercode character varying(5),
    scheddate date,
    schedhour integer,
    deptcode character varying(10),
    researchercode character varying(20),
    time_used boolean,
    scannercode_old character varying(5),
    scheddate_old date,
    schedhour_old integer,
    deptcode_old character varying(10),
    researchercode_old character varying(20),
    time_used_old boolean,
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone,
    chg_by character varying(30)
);


--
-- Name: TABLE tlogsched; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tlogsched IS 'Logged changes from tblsched';


--
-- Name: COLUMN tlogsched.logid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.logid IS 'primary key';


--
-- Name: COLUMN tlogsched.schedid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.schedid IS 'schedid for logged value, new entries always reference a row in tblsched';


--
-- Name: COLUMN tlogsched.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.scannercode IS 'value of tblsched.scannercode';


--
-- Name: COLUMN tlogsched.scheddate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.scheddate IS 'value of tblsched.scheddate';


--
-- Name: COLUMN tlogsched.schedhour; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.schedhour IS 'value of tblsched.schedhour';


--
-- Name: COLUMN tlogsched.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.deptcode IS 'value of tblsched.deptcode';


--
-- Name: COLUMN tlogsched.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.researchercode IS 'value of tblsched.researchercode';


--
-- Name: COLUMN tlogsched.time_used; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.time_used IS 'value of tblsched.time_used';


--
-- Name: COLUMN tlogsched.scannercode_old; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.scannercode_old IS 'previous value of tblsched.scannercode';


--
-- Name: COLUMN tlogsched.scheddate_old; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.scheddate_old IS 'previous value of tblsched.scheddate';


--
-- Name: COLUMN tlogsched.schedhour_old; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.schedhour_old IS 'previous value of tblsched.schedhour';


--
-- Name: COLUMN tlogsched.deptcode_old; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.deptcode_old IS 'previous value of tblsched.deptcode';


--
-- Name: COLUMN tlogsched.researchercode_old; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.researchercode_old IS 'previous value of tblsched.researchercode';


--
-- Name: COLUMN tlogsched.time_used_old; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.time_used_old IS 'previous value of tblsched.time_used';


--
-- Name: COLUMN tlogsched.chg_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.chg_at IS 'value of tblsched.chg_at';


--
-- Name: COLUMN tlogsched.chg_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlogsched.chg_by IS 'value of tblsched.chg_by';


--
-- Name: app_log_json; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.app_log_json AS
 WITH regular_entries AS (
         SELECT tlogsched.schedid,
            tlogsched.chg_at AS modified,
            'main'::text AS kind,
            (COALESCE(tlogsched.chg_by, ''::character varying))::text AS chg_by,
            json_strip_nulls(json_build_object('researcher',
                CASE
                    WHEN ((tlogsched.researchercode_old)::text IS DISTINCT FROM (tlogsched.researchercode)::text) THEN json_build_array(tlogsched.researchercode_old, tlogsched.researchercode)
                    ELSE NULL::json
                END, 'group',
                CASE
                    WHEN ((tlogsched.deptcode_old)::text IS DISTINCT FROM (tlogsched.deptcode)::text) THEN json_build_array(tlogsched.deptcode_old, tlogsched.deptcode)
                    ELSE NULL::json
                END, 'used',
                CASE
                    WHEN (tlogsched.time_used_old IS DISTINCT FROM tlogsched.time_used) THEN json_build_array(tlogsched.time_used_old, tlogsched.time_used)
                    ELSE NULL::json
                END)) AS "values"
           FROM public.tlogsched
          WHERE ((tlogsched.schedid IS NOT NULL) AND (tlogsched.chg_at IS NOT NULL))
        ), support_entries AS (
         SELECT supportlog.schedid,
            supportlog.chg_at AS modified,
            supportkind.label AS kind,
            (supportlog.chg_by)::text AS chg_by,
            json_strip_nulls(json_build_object('filed_by',
                CASE
                    WHEN ((supportlog.filed_by_old)::text IS DISTINCT FROM (supportlog.filed_by)::text) THEN json_build_array(supportlog.filed_by_old, supportlog.filed_by)
                    ELSE NULL::json
                END, 'fulfilled_by',
                CASE
                    WHEN ((supportlog.fulfilled_by_old)::text IS DISTINCT FROM (supportlog.fulfilled_by)::text) THEN json_build_array(supportlog.fulfilled_by_old, supportlog.fulfilled_by)
                    ELSE NULL::json
                END, 'approved',
                CASE
                    WHEN (supportlog.approved_old IS DISTINCT FROM supportlog.approved) THEN json_build_array(supportlog.approved_old, supportlog.approved)
                    ELSE NULL::json
                END, 'note',
                CASE
                    WHEN (supportlog.note_old IS DISTINCT FROM supportlog.note) THEN json_build_array(supportlog.note_old, supportlog.note)
                    ELSE NULL::json
                END)) AS "values"
           FROM (public.supportlog
             JOIN public.supportkind USING (supportkind))
        ), combined_entries AS (
         SELECT regular_entries.schedid,
            regular_entries.modified,
            regular_entries.kind,
            regular_entries.chg_by,
            regular_entries."values"
           FROM regular_entries
        UNION ALL
         SELECT support_entries.schedid,
            support_entries.modified,
            support_entries.kind,
            support_entries.chg_by,
            support_entries."values"
           FROM support_entries
        ), filtered_and_sorted_entries AS (
         SELECT combined_entries.schedid,
            json_build_object('modified', combined_entries.modified, 'kind', combined_entries.kind, 'values', combined_entries."values") AS entries
           FROM combined_entries
          WHERE (length((combined_entries."values")::text) > 2)
          ORDER BY combined_entries.modified
        )
 SELECT filtered_and_sorted_entries.schedid,
    json_agg(filtered_and_sorted_entries.entries) AS entries
   FROM filtered_and_sorted_entries
  GROUP BY filtered_and_sorted_entries.schedid;


--
-- Name: VIEW app_log_json; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.app_log_json IS 'get json of all log entries - always call with "where schedid = "!';


--
-- Name: COLUMN app_log_json.schedid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.app_log_json.schedid IS 'the schedid of the log entries - MUST specify this in where clause!';


--
-- Name: COLUMN app_log_json.entries; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.app_log_json.entries IS 'json of all log entries for selected schedid';


--
-- Name: devicegroup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.devicegroup (
    scannercode character varying(5) NOT NULL,
    deptcode character varying(10) NOT NULL
);


--
-- Name: TABLE devicegroup; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.devicegroup IS 'device ↔ group';


--
-- Name: COLUMN devicegroup.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.devicegroup.scannercode IS 'first half of primary key';


--
-- Name: COLUMN devicegroup.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.devicegroup.deptcode IS 'second half of primary key';


--
-- Name: groupmembers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.groupmembers (
    deptcode character varying(10) NOT NULL,
    researchercode character varying(20) NOT NULL,
    approve1 timestamp with time zone,
    approve2 timestamp with time zone,
    approved boolean GENERATED ALWAYS AS (((approve1 IS NOT NULL) AND (approve2 IS NOT NULL))) STORED NOT NULL
);


--
-- Name: TABLE groupmembers; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.groupmembers IS 'group ↔ user';


--
-- Name: COLUMN groupmembers.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.groupmembers.deptcode IS 'first half of primary key';


--
-- Name: COLUMN groupmembers.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.groupmembers.researchercode IS 'second half of primary key';


--
-- Name: COLUMN groupmembers.approve1; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.groupmembers.approve1 IS 'approval to join (type 1)';


--
-- Name: COLUMN groupmembers.approve2; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.groupmembers.approve2 IS 'approval to join (type 2)';


--
-- Name: COLUMN groupmembers.approved; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.groupmembers.approved IS 'true if approved member of group';


--
-- Name: primarygroupmember; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.primarygroupmember (
    deptcode character varying(10) NOT NULL,
    researchercode character varying(20) NOT NULL
);


--
-- Name: TABLE primarygroupmember; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.primarygroupmember IS 'primary investigator of group';


--
-- Name: COLUMN primarygroupmember.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.primarygroupmember.deptcode IS 'first half of primary key';


--
-- Name: COLUMN primarygroupmember.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.primarygroupmember.researchercode IS 'second half of primary key';


--
-- Name: tlkpdept; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tlkpdept (
    deptcode character varying(10) NOT NULL,
    dept character varying(75) NOT NULL COLLATE pg_catalog."en-US-x-icu",
    dept_short character varying(20) NOT NULL,
    grp character varying(10) DEFAULT ''::character varying NOT NULL,
    ismain boolean DEFAULT true NOT NULL,
    iscurrent boolean DEFAULT true NOT NULL,
    inst character varying(5),
    prog character varying(10) DEFAULT ''::character varying NOT NULL,
    link text DEFAULT ''::text NOT NULL,
    pi character varying(50),
    lose_to character varying(10),
    email text DEFAULT ''::text NOT NULL,
    color character varying(7) NOT NULL,
    joinable boolean DEFAULT true NOT NULL,
    archivable boolean DEFAULT true NOT NULL,
    scheduleable boolean DEFAULT true NOT NULL,
    department boolean GENERATED ALWAYS AS ((ismain AND archivable AND scheduleable)) STORED NOT NULL,
    CONSTRAINT tlkpdept_valid_color CHECK (((color)::text ~ '^#[0-9a-f]{6}$'::text))
);


--
-- Name: TABLE tlkpdept; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tlkpdept IS 'List of groups';


--
-- Name: COLUMN tlkpdept.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.deptcode IS 'primary key';


--
-- Name: COLUMN tlkpdept.dept; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.dept IS 'human readable name of department (long)';


--
-- Name: COLUMN tlkpdept.dept_short; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.dept_short IS 'human readable name of department (short)';


--
-- Name: COLUMN tlkpdept.grp; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.grp IS 'Deprecated';


--
-- Name: COLUMN tlkpdept.ismain; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.ismain IS 'true for groups with membership';


--
-- Name: COLUMN tlkpdept.iscurrent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.iscurrent IS 'Is this department active';


--
-- Name: COLUMN tlkpdept.inst; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.inst IS 'optional reference to tlkpinst';


--
-- Name: COLUMN tlkpdept.prog; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.prog IS 'Deprecated';


--
-- Name: COLUMN tlkpdept.link; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.link IS 'Link to the Unit/Section''s home page';


--
-- Name: COLUMN tlkpdept.pi; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.pi IS 'Deprecated';


--
-- Name: COLUMN tlkpdept.lose_to; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.lose_to IS 'Deprecated';


--
-- Name: COLUMN tlkpdept.email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.email IS 'contact address for department';


--
-- Name: COLUMN tlkpdept.color; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.color IS 'legend color on site';


--
-- Name: COLUMN tlkpdept.joinable; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.joinable IS 'true for groups that users may join';


--
-- Name: COLUMN tlkpdept.archivable; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.archivable IS 'true for user created groups that may be archived';


--
-- Name: COLUMN tlkpdept.scheduleable; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.scheduleable IS 'true for groups that may be referenced in tblsched';


--
-- Name: COLUMN tlkpdept.department; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpdept.department IS 'true for department and false for a special group';


--
-- Name: tlkpresearcher; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tlkpresearcher (
    researchercode character varying(20) NOT NULL,
    lname character varying(20),
    fname character varying(20),
    dept_code character varying(10),
    researchershort character varying(15),
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone NOT NULL,
    chg_by character varying(30),
    lose_to character varying(15),
    active boolean DEFAULT true NOT NULL,
    name text DEFAULT ''::text NOT NULL,
    email text DEFAULT ''::text NOT NULL
);


--
-- Name: TABLE tlkpresearcher; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tlkpresearcher IS 'List of users';


--
-- Name: COLUMN tlkpresearcher.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.researchercode IS 'primary key';


--
-- Name: COLUMN tlkpresearcher.lname; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.lname IS 'Deprecated';


--
-- Name: COLUMN tlkpresearcher.fname; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.fname IS 'Deprecated';


--
-- Name: COLUMN tlkpresearcher.dept_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.dept_code IS 'Deprecated';


--
-- Name: COLUMN tlkpresearcher.researchershort; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.researchershort IS 'Deprecated';


--
-- Name: COLUMN tlkpresearcher.chg_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.chg_at IS 'timestamp of last modification';


--
-- Name: COLUMN tlkpresearcher.chg_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.chg_by IS 'Deprecated';


--
-- Name: COLUMN tlkpresearcher.lose_to; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.lose_to IS 'Deprecated';


--
-- Name: COLUMN tlkpresearcher.active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.active IS 'if not active, no longer be an option anywhere until marked active again';


--
-- Name: COLUMN tlkpresearcher.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.name IS 'Full name as reported by AD';


--
-- Name: COLUMN tlkpresearcher.email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpresearcher.email IS 'email address as reported by AD';


--
-- Name: membership; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.membership AS
 SELECT m.deptcode AS "group",
    m.researchercode AS "user",
        CASE
            WHEN (p.deptcode IS NOT NULL) THEN true
            ELSE false
        END AS pi,
    m.approved,
    d.iscurrent AS group_active,
    r.active AS user_active
   FROM (((public.groupmembers m
     JOIN public.tlkpdept d USING (deptcode))
     JOIN public.tlkpresearcher r USING (researchercode))
     LEFT JOIN public.primarygroupmember p USING (deptcode, researchercode))
  ORDER BY m.deptcode,
        CASE
            WHEN (p.deptcode IS NOT NULL) THEN true
            ELSE false
        END DESC, m.researchercode;


--
-- Name: VIEW membership; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.membership IS 'all membership data joined together';


--
-- Name: COLUMN membership."group"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.membership."group" IS 'pk for the group';


--
-- Name: COLUMN membership."user"; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.membership."user" IS 'pk for the user';


--
-- Name: COLUMN membership.pi; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.membership.pi IS 'is this user the pi of the group';


--
-- Name: COLUMN membership.approved; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.membership.approved IS 'is this user an approved member of the group';


--
-- Name: COLUMN membership.group_active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.membership.group_active IS 'is this group active';


--
-- Name: COLUMN membership.user_active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.membership.user_active IS 'is this user active';


--
-- Name: reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reset_tokens (
    token text NOT NULL,
    for_user character varying(20) NOT NULL,
    issued timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: TABLE reset_tokens; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.reset_tokens IS 'an internal store for the website, ignore';


--
-- Name: site_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.site_sessions (
    id integer NOT NULL,
    session_id character varying(255),
    data bytea,
    expiry timestamp without time zone
);


--
-- Name: TABLE site_sessions; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.site_sessions IS 'an internal session store for the website, ignore';


--
-- Name: site_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.site_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: site_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.site_sessions_id_seq OWNED BY public.site_sessions.id;


--
-- Name: support; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.support (
    schedid integer NOT NULL,
    supportkind integer NOT NULL,
    filed_by character varying(20) NOT NULL,
    fulfilled_by character varying(20),
    approved boolean,
    note text DEFAULT ''::text NOT NULL,
    chg_by character varying(20) NOT NULL,
    chg_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: TABLE support; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.support IS 'support requests for slot';


--
-- Name: COLUMN support.schedid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.schedid IS 'first half of primary key';


--
-- Name: COLUMN support.supportkind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.supportkind IS 'second half of primary key';


--
-- Name: COLUMN support.filed_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.filed_by IS 'user who filed this request';


--
-- Name: COLUMN support.fulfilled_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.fulfilled_by IS 'user who will fulfill this request';


--
-- Name: COLUMN support.approved; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.approved IS 'whether this request has been approved (null = not yet decided)';


--
-- Name: COLUMN support.note; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.note IS 'used by technologist requests to disambiguate cover/scan requests';


--
-- Name: COLUMN support.chg_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.chg_by IS 'user who last modified this request';


--
-- Name: COLUMN support.chg_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.support.chg_at IS 'timestamp of last modification';


--
-- Name: supportkind_supportkind_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.supportkind ALTER COLUMN supportkind ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.supportkind_supportkind_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: supportlog_logid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.supportlog ALTER COLUMN logid ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.supportlog_logid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tblsched; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tblsched (
    schedid integer DEFAULT nextval(('"tblsched_schedid_seq"'::text)::regclass) NOT NULL,
    scannercode character varying(5) NOT NULL,
    scheddate date NOT NULL,
    scheddow integer NOT NULL,
    schedhour integer NOT NULL,
    deptcode character varying(10),
    researchercode character varying(20),
    time_used boolean,
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone,
    chg_by character varying(30),
    billdeptcode character varying(10),
    templateid integer,
    post_on timestamp without time zone,
    orig_deptcode character varying(10),
    orig_instcode character varying(5),
    CONSTRAINT tblsched_scheddow CHECK (((scheddow >= 0) AND (scheddow <= 6))),
    CONSTRAINT tblsched_schedhour CHECK (((schedhour >= 0) AND (schedhour <= 23)))
);


--
-- Name: TABLE tblsched; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tblsched IS 'Schedule assignments';


--
-- Name: COLUMN tblsched.schedid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.schedid IS 'primary key';


--
-- Name: COLUMN tblsched.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.scannercode IS 'reference to tlkpscanner';


--
-- Name: COLUMN tblsched.scheddate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.scheddate IS 'civil date of assignment';


--
-- Name: COLUMN tblsched.scheddow; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.scheddow IS 'day of the week of assignment (0 = Sunday)';


--
-- Name: COLUMN tblsched.schedhour; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.schedhour IS '0-indexed 24 hour civil time of assignment';


--
-- Name: COLUMN tblsched.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.deptcode IS 'optional reference to tlkpdept currently assigned';


--
-- Name: COLUMN tblsched.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.researchercode IS 'optional reference to tlkpresearcher currently assigned';


--
-- Name: COLUMN tblsched.time_used; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.time_used IS 'null initially and periodically set to true or false by DICOM sync';


--
-- Name: COLUMN tblsched.chg_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.chg_at IS 'timestamp of last modification';


--
-- Name: COLUMN tblsched.chg_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.chg_by IS 'description of last entity to change this row';


--
-- Name: COLUMN tblsched.billdeptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.billdeptcode IS 'Deprecated';


--
-- Name: COLUMN tblsched.templateid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.templateid IS 'reference to tbltemplate that created this row (optional for historical reasons)';


--
-- Name: COLUMN tblsched.post_on; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.post_on IS 'Deprecated';


--
-- Name: COLUMN tblsched.orig_deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.orig_deptcode IS 'optional reference to tlkpresearcher originally assigned';


--
-- Name: COLUMN tblsched.orig_instcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tblsched.orig_instcode IS 'optional reference to tlkpinst originally assigned';


--
-- Name: tblsched_schedid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tblsched_schedid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 2147483647
    CACHE 1;


--
-- Name: tbltemplate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tbltemplate (
    templateid integer DEFAULT nextval(('"tbltemplate_templateid_seq"'::text)::regclass) NOT NULL,
    scannercode character varying(5) NOT NULL,
    dow integer NOT NULL,
    hour integer NOT NULL,
    deptcode character varying(10),
    researchercode character varying(20),
    templatecode character varying(1) NOT NULL,
    instcode character varying(5),
    CONSTRAINT tbltemplate_dow CHECK (((dow >= 0) AND (dow <= 6))),
    CONSTRAINT tbltemplate_hour CHECK (((hour >= 0) AND (hour <= 23)))
);


--
-- Name: TABLE tbltemplate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tbltemplate IS 'Templated times for scanner use';


--
-- Name: COLUMN tbltemplate.templateid; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.templateid IS 'primary key';


--
-- Name: COLUMN tbltemplate.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.scannercode IS 'reference to tlkpscanner';


--
-- Name: COLUMN tbltemplate.dow; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.dow IS 'day of the week (0 = Sunday) of assignment';


--
-- Name: COLUMN tbltemplate.hour; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.hour IS '0-indexed 24 hour civil time of assignment';


--
-- Name: COLUMN tbltemplate.deptcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.deptcode IS 'optional reference to tlkpdept assigned';


--
-- Name: COLUMN tbltemplate.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.researchercode IS 'optional reference to tlkpresearcher assigned';


--
-- Name: COLUMN tbltemplate.templatecode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.templatecode IS 'with scannercode, references tbltemplates';


--
-- Name: COLUMN tbltemplate.instcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplate.instcode IS 'optional reference to tlkpinst assigned';


--
-- Name: tbltemplate_templateid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tbltemplate_templateid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    MAXVALUE 2147483647
    CACHE 1;


--
-- Name: tbltemplates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tbltemplates (
    templatecode character varying(1) NOT NULL,
    scannercode character varying(5) NOT NULL,
    template character varying(25) NOT NULL,
    comments text DEFAULT ''::text NOT NULL COLLATE pg_catalog."en-US-x-icu",
    hidden boolean DEFAULT false NOT NULL
);


--
-- Name: TABLE tbltemplates; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tbltemplates IS 'List of scanner templates';


--
-- Name: COLUMN tbltemplates.templatecode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplates.templatecode IS 'unique half of primary key';


--
-- Name: COLUMN tbltemplates.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplates.scannercode IS 'reference to tlkpscanner and other half of primary key';


--
-- Name: COLUMN tbltemplates.template; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplates.template IS 'human readable name of template';


--
-- Name: COLUMN tbltemplates.comments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplates.comments IS 'human readable notes about template';


--
-- Name: COLUMN tbltemplates.hidden; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tbltemplates.hidden IS 'if hidden, the template is no longer available to create schedules';


--
-- Name: technicalscans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.technicalscans (
    tsid integer NOT NULL,
    subject character varying(50) NOT NULL,
    scantime timestamp without time zone NOT NULL,
    scannercode character varying(10) NOT NULL,
    deptcode character varying(10) NOT NULL,
    comments text,
    fullname character varying(50)
);


--
-- Name: TABLE technicalscans; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.technicalscans IS 'Deprecated';


--
-- Name: technicalscans_tsid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.technicalscans_tsid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: technicalscans_tsid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.technicalscans_tsid_seq OWNED BY public.technicalscans.tsid;


--
-- Name: tlkpinst; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tlkpinst (
    instcode character varying(5) NOT NULL,
    inst character varying(20) DEFAULT ''::character varying NOT NULL,
    active boolean DEFAULT true NOT NULL
);


--
-- Name: TABLE tlkpinst; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tlkpinst IS 'List of institutes';


--
-- Name: COLUMN tlkpinst.instcode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpinst.instcode IS 'primary key';


--
-- Name: COLUMN tlkpinst.inst; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpinst.inst IS 'human readable name of institute';


--
-- Name: COLUMN tlkpinst.active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpinst.active IS 'if not active, the institute is no longer available for selection';


--
-- Name: tlkpscanner; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tlkpscanner (
    scannercode character varying(5) NOT NULL,
    scanner character varying(25) NOT NULL,
    descrip text DEFAULT ''::text NOT NULL COLLATE pg_catalog."en-US-x-icu",
    mailinglist text DEFAULT ''::text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    techaddr text DEFAULT ''::text NOT NULL,
    medaddr text DEFAULT ''::text NOT NULL,
    trainaddr text DEFAULT ''::text NOT NULL
);


--
-- Name: TABLE tlkpscanner; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tlkpscanner IS 'List of devices';


--
-- Name: COLUMN tlkpscanner.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.scannercode IS 'primary key';


--
-- Name: COLUMN tlkpscanner.scanner; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.scanner IS 'human readable label of device';


--
-- Name: COLUMN tlkpscanner.descrip; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.descrip IS 'description of device';


--
-- Name: COLUMN tlkpscanner.mailinglist; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.mailinglist IS 'contact address for device';


--
-- Name: COLUMN tlkpscanner.active; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.active IS 'if not active, no long an option anywhere';


--
-- Name: COLUMN tlkpscanner.techaddr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.techaddr IS 'contact address for technologist requests';


--
-- Name: COLUMN tlkpscanner.medaddr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.medaddr IS 'contact address for medical coverage requests';


--
-- Name: COLUMN tlkpscanner.trainaddr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tlkpscanner.trainaddr IS 'contact address for training requests';


--
-- Name: tlogresearcher; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tlogresearcher (
    logid integer NOT NULL,
    researchercode character varying(15),
    lname character varying(20),
    fname character varying(20),
    researchershort character varying(15),
    dept_code character varying(10),
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone,
    chg_by character varying(30),
    researchercode_old character varying(15),
    lname_old character varying(20),
    fname_old character varying(20),
    researchershort_old character varying(15),
    dept_code__old character varying(10)
);


--
-- Name: TABLE tlogresearcher; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tlogresearcher IS 'Deprecated';


--
-- Name: tlogresearcher_logid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tlogresearcher_logid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tlogresearcher_logid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tlogresearcher_logid_seq OWNED BY public.tlogresearcher.logid;


--
-- Name: tlogsched_logid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tlogsched_logid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tlogsched_logid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tlogsched_logid_seq OWNED BY public.tlogsched.logid;


--
-- Name: userdevice; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.userdevice (
    researchercode character varying(20) NOT NULL,
    scannercode character varying(5) NOT NULL,
    templates boolean NOT NULL,
    slot boolean NOT NULL,
    tech boolean NOT NULL,
    medical boolean NOT NULL,
    training boolean NOT NULL,
    CONSTRAINT userdevice_at_least_one_permission CHECK ((templates OR slot OR tech OR medical OR training))
);


--
-- Name: TABLE userdevice; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.userdevice IS 'user ↔ device dev group permissions';


--
-- Name: COLUMN userdevice.researchercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.researchercode IS 'first half of primary key';


--
-- Name: COLUMN userdevice.scannercode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.scannercode IS 'second half of primary key';


--
-- Name: COLUMN userdevice.templates; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.templates IS 'permission to edit and apply templates on this device';


--
-- Name: COLUMN userdevice.slot; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.slot IS 'permission to edit any slot on this device';


--
-- Name: COLUMN userdevice.tech; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.tech IS 'permission to respond to requests for technologist on this device';


--
-- Name: COLUMN userdevice.medical; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.medical IS 'permission to respond to requests for medical coverage on this device';


--
-- Name: COLUMN userdevice.training; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.userdevice.training IS 'permission to respond to requests for training on this device';


--
-- Name: site_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.site_sessions ALTER COLUMN id SET DEFAULT nextval('public.site_sessions_id_seq'::regclass);


--
-- Name: technicalscans tsid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.technicalscans ALTER COLUMN tsid SET DEFAULT nextval('public.technicalscans_tsid_seq'::regclass);


--
-- Name: tlogresearcher logid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlogresearcher ALTER COLUMN logid SET DEFAULT nextval('public.tlogresearcher_logid_seq'::regclass);


--
-- Name: tlogsched logid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlogsched ALTER COLUMN logid SET DEFAULT nextval('public.tlogsched_logid_seq'::regclass);


--
-- Name: devicegroup devicegroup_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devicegroup
    ADD CONSTRAINT devicegroup_pkey PRIMARY KEY (scannercode, deptcode);


--
-- Name: groupmembers groupmembers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.groupmembers
    ADD CONSTRAINT groupmembers_pkey PRIMARY KEY (deptcode, researchercode);


--
-- Name: primarygroupmember primarygroupmember_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primarygroupmember
    ADD CONSTRAINT primarygroupmember_pkey PRIMARY KEY (deptcode);


--
-- Name: reset_tokens reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reset_tokens
    ADD CONSTRAINT reset_tokens_pkey PRIMARY KEY (token);


--
-- Name: site_sessions site_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.site_sessions
    ADD CONSTRAINT site_sessions_pkey PRIMARY KEY (id);


--
-- Name: site_sessions site_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.site_sessions
    ADD CONSTRAINT site_sessions_session_id_key UNIQUE (session_id);


--
-- Name: support support_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.support
    ADD CONSTRAINT support_pkey PRIMARY KEY (schedid, supportkind);


--
-- Name: supportkind supportkind_label_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supportkind
    ADD CONSTRAINT supportkind_label_key UNIQUE (label);


--
-- Name: supportkind supportkind_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supportkind
    ADD CONSTRAINT supportkind_pkey PRIMARY KEY (supportkind);


--
-- Name: supportlog supportlog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supportlog
    ADD CONSTRAINT supportlog_pkey PRIMARY KEY (logid);


--
-- Name: tblsched tblsched_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_pkey PRIMARY KEY (schedid);


--
-- Name: tbltemplate tbltemplate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_pkey PRIMARY KEY (templateid);


--
-- Name: tbltemplate tbltemplate_scannercode_key1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_scannercode_key1 UNIQUE (scannercode, templatecode, dow, hour);


--
-- Name: tbltemplates tbltemplates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplates
    ADD CONSTRAINT tbltemplates_pkey PRIMARY KEY (templatecode, scannercode);


--
-- Name: technicalscans technicalscans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.technicalscans
    ADD CONSTRAINT technicalscans_pkey PRIMARY KEY (tsid);


--
-- Name: tlkpdept tlkpdept_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlkpdept
    ADD CONSTRAINT tlkpdept_pkey PRIMARY KEY (deptcode);


--
-- Name: tlkpinst tlkpinst_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlkpinst
    ADD CONSTRAINT tlkpinst_pkey PRIMARY KEY (instcode);


--
-- Name: tlkpresearcher tlkpresearcher_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlkpresearcher
    ADD CONSTRAINT tlkpresearcher_pkey PRIMARY KEY (researchercode);


--
-- Name: tlkpscanner tlkpscanner_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlkpscanner
    ADD CONSTRAINT tlkpscanner_pkey PRIMARY KEY (scannercode);


--
-- Name: tlogresearcher tlogresearcher_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlogresearcher
    ADD CONSTRAINT tlogresearcher_pkey PRIMARY KEY (logid);


--
-- Name: userdevice userdevice_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.userdevice
    ADD CONSTRAINT userdevice_pkey PRIMARY KEY (researchercode, scannercode);


--
-- Name: tblsched_scannercode_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tblsched_scannercode_key ON public.tblsched USING btree (scannercode, scheddate, schedhour);


--
-- Name: tlkpdept_dept_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tlkpdept_dept_key ON public.tlkpdept USING btree (dept);


--
-- Name: tlkpdept_dept_short_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tlkpdept_dept_short_key ON public.tlkpdept USING btree (dept_short);


--
-- Name: tlkpscanner_scanner_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX tlkpscanner_scanner_key ON public.tlkpscanner USING btree (scanner);


--
-- Name: tlkpinst delete_inst; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER delete_inst BEFORE DELETE ON public.tlkpinst FOR EACH ROW EXECUTE FUNCTION public.soft_del_inst();


--
-- Name: TRIGGER delete_inst ON tlkpinst; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TRIGGER delete_inst ON public.tlkpinst IS 'make deletes on tlkpinst set hidden = true instead';


--
-- Name: tblsched log_sched_changes; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER log_sched_changes AFTER INSERT OR DELETE OR UPDATE ON public.tblsched FOR EACH ROW EXECUTE FUNCTION public.log_sched_changes_impl();


--
-- Name: support log_support_changes; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER log_support_changes AFTER INSERT OR UPDATE ON public.support FOR EACH ROW EXECUTE FUNCTION public.log_support_impl();


--
-- Name: devicegroup groupdevice_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devicegroup
    ADD CONSTRAINT groupdevice_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES public.tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: devicegroup groupdevice_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.devicegroup
    ADD CONSTRAINT groupdevice_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES public.tlkpscanner(scannercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: groupmembers groupmembers_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.groupmembers
    ADD CONSTRAINT groupmembers_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES public.tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: groupmembers groupmembers_researchercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.groupmembers
    ADD CONSTRAINT groupmembers_researchercode_fkey FOREIGN KEY (researchercode) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: primarygroupmember primarygroupmember_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primarygroupmember
    ADD CONSTRAINT primarygroupmember_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES public.tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: primarygroupmember primarygroupmember_groupmembers_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primarygroupmember
    ADD CONSTRAINT primarygroupmember_groupmembers_fkey FOREIGN KEY (deptcode, researchercode) REFERENCES public.groupmembers(deptcode, researchercode) ON DELETE RESTRICT;


--
-- Name: primarygroupmember primarygroupmember_researchercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.primarygroupmember
    ADD CONSTRAINT primarygroupmember_researchercode_fkey FOREIGN KEY (researchercode) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: reset_tokens reset_tokens_for_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reset_tokens
    ADD CONSTRAINT reset_tokens_for_user_fkey FOREIGN KEY (for_user) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: support support_chg_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.support
    ADD CONSTRAINT support_chg_by_fkey FOREIGN KEY (chg_by) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: support support_filed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.support
    ADD CONSTRAINT support_filed_by_fkey FOREIGN KEY (filed_by) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: support support_fulfilled_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.support
    ADD CONSTRAINT support_fulfilled_by_fkey FOREIGN KEY (fulfilled_by) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: support support_schedid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.support
    ADD CONSTRAINT support_schedid_fkey FOREIGN KEY (schedid) REFERENCES public.tblsched(schedid) ON DELETE RESTRICT;


--
-- Name: support support_supportkind_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.support
    ADD CONSTRAINT support_supportkind_fkey FOREIGN KEY (supportkind) REFERENCES public.supportkind(supportkind) ON DELETE RESTRICT;


--
-- Name: supportlog supportlog_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supportlog
    ADD CONSTRAINT supportlog_fkey FOREIGN KEY (schedid, supportkind) REFERENCES public.support(schedid, supportkind) ON DELETE CASCADE;


--
-- Name: tblsched tblsched_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES public.tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tblsched tblsched_instcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_instcode_fkey FOREIGN KEY (orig_instcode) REFERENCES public.tlkpinst(instcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tblsched tblsched_orig_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_orig_deptcode_fkey FOREIGN KEY (orig_deptcode) REFERENCES public.tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tblsched tblsched_orig_inst_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_orig_inst_fkey FOREIGN KEY (orig_instcode) REFERENCES public.tlkpinst(instcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tblsched tblsched_researchercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_researchercode_fkey FOREIGN KEY (researchercode) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tblsched tblsched_scanner_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_scanner_fkey FOREIGN KEY (scannercode) REFERENCES public.tlkpscanner(scannercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tblsched tblsched_templateid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tblsched
    ADD CONSTRAINT tblsched_templateid_fkey FOREIGN KEY (templateid) REFERENCES public.tbltemplate(templateid) ON DELETE SET NULL;


--
-- Name: tbltemplate tbltemplate_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES public.tlkpdept(deptcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tbltemplate tbltemplate_instcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_instcode_fkey FOREIGN KEY (instcode) REFERENCES public.tlkpinst(instcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tbltemplate tbltemplate_researchercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_researchercode_fkey FOREIGN KEY (researchercode) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tbltemplate tbltemplate_scanner_and_templatecode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_scanner_and_templatecode_fkey FOREIGN KEY (scannercode, templatecode) REFERENCES public.tbltemplates(scannercode, templatecode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tbltemplate tbltemplate_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplate
    ADD CONSTRAINT tbltemplate_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES public.tlkpscanner(scannercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tbltemplates tbltemplates_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tbltemplates
    ADD CONSTRAINT tbltemplates_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES public.tlkpscanner(scannercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tlkpdept tlkpdept_inst_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tlkpdept
    ADD CONSTRAINT tlkpdept_inst_fkey FOREIGN KEY (inst) REFERENCES public.tlkpinst(instcode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: userdevice userdevice_researchercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.userdevice
    ADD CONSTRAINT userdevice_researchercode_fkey FOREIGN KEY (researchercode) REFERENCES public.tlkpresearcher(researchercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: userdevice userdevice_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.userdevice
    ADD CONSTRAINT userdevice_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES public.tlkpscanner(scannercode) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

