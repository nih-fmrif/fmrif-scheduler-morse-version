--
-- PostgreSQL database dump
--

SET client_encoding = 'SQL_ASCII';
SET check_function_bodies = false;
SET client_min_messages = warning;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: postgres
--

COMMENT ON SCHEMA public IS 'Standard public schema';


--
-- Name: plpgsql; Type: PROCEDURAL LANGUAGE; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql;


SET search_path = public, pg_catalog;

--
-- Name: foof(); Type: FUNCTION; Schema: public; Owner: jburton
--

CREATE FUNCTION foof() RETURNS record
    AS $$ create temporary table z as select 1; select * from z; $$
    LANGUAGE sql;


--
-- Name: template_default_fill(character varying, character varying); Type: FUNCTION; Schema: public; Owner: jburton
--

CREATE FUNCTION template_default_fill(character varying, character varying) RETURNS boolean
    AS $_$begin for thedow in 0..6 loop for thehour in 0..23 loop insert into tbltemplate (templatecode, scannercode, dow, hour, deptcode) values ($2, $1, thedow, thehour, ''); end loop; end loop; return true; end;$_$
    LANGUAGE plpgsql;


--
-- Name: template_to_sched(character varying, character varying, date, date); Type: FUNCTION; Schema: public; Owner: jburton
--

CREATE FUNCTION template_to_sched(character varying, character varying, date, date) RETURNS boolean
    AS $_$
declare
  the_scannercode alias for $1;
  the_templatecode alias for $2;
  start_date alias for $3;
  end_date alias for $4;
  the_date date;
  the_dow int;
begin
  the_date := start_date;
  delete from tblsched where scannercode=the_scannercode and scheddate between start_date and end_date;
  while the_date <= end_date
  loop
    the_dow := extract(dow from the_date);
    insert into tblsched(scannercode,deptcode,researchercode,scheddate,schedhour,scheddow,billdeptcode,templateid,orig_deptcode,orig_instcode)
      select scannercode,deptcode,researchercode,the_date,hour,the_dow,deptcode,templateid,deptcode,instcode from tbltemplate
        where dow=the_dow and scannercode = the_scannercode and templatecode=the_templatecode;
    the_date = the_date + 1;
  end loop;
  return true;
end;
$_$
    LANGUAGE plpgsql;


SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: tlkpdept; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tlkpdept (
    deptcode character varying(10) NOT NULL,
    dept character varying(75) NOT NULL,
    dept_short character varying(20) NOT NULL,
    grp character varying(10) NOT NULL,
    color_wkday_day character varying(6),
    color_wkday_eve character varying(6),
    color_wkend_day character varying(6),
    color_wkend_eve character varying(6),
    ismain boolean DEFAULT true,
    iscurrent boolean DEFAULT true,
    inst character varying(5),
    prog character varying(10),
    link text,
    pi character varying(50),
    lose_to character varying(10),
    email character varying(2000)
);


--
-- Name: TABLE tlkpdept; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tlkpdept IS 'List of departments';


--
-- Name: COLUMN tlkpdept.grp; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.grp IS 'Group this falls in (ie, top-level department)';


--
-- Name: COLUMN tlkpdept.color_wkday_day; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.color_wkday_day IS 'Color for dept (for all times, despite name!)';


--
-- Name: COLUMN tlkpdept.color_wkday_eve; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.color_wkday_eve IS 'UNUSED LEGACY';


--
-- Name: COLUMN tlkpdept.color_wkend_day; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.color_wkend_day IS 'UNUSED LEGACY';


--
-- Name: COLUMN tlkpdept.color_wkend_eve; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.color_wkend_eve IS 'UNUSED LEGACY';


--
-- Name: COLUMN tlkpdept.ismain; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.ismain IS 'Should this appear as "top-level" department (in legend, etc.)';


--
-- Name: COLUMN tlkpdept.iscurrent; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.iscurrent IS 'Is this department active';


--
-- Name: COLUMN tlkpdept.inst; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.inst IS 'Institute (NIMH, NINDS, NCI, etc)';


--
-- Name: COLUMN tlkpdept.prog; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.prog IS 'Program and Branch';


--
-- Name: COLUMN tlkpdept.link; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.link IS 'Link to the Unit/Section''s home page';


--
-- Name: COLUMN tlkpdept.pi; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpdept.pi IS 'Name of the primary investigatior in charge of the lab';


--
-- Name: departments; Type: VIEW; Schema: public; Owner: jburton
--

CREATE VIEW departments AS
    SELECT tlkpdept.deptcode, tlkpdept.dept, tlkpdept.dept_short, tlkpdept.grp, tlkpdept.color_wkday_day AS color FROM tlkpdept WHERE (tlkpdept.ismain AND tlkpdept.iscurrent) ORDER BY tlkpdept.deptcode;


--
-- Name: VIEW departments; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON VIEW departments IS 'Current, real departments';


--
-- Name: departments_agt; Type: VIEW; Schema: public; Owner: adamt
--

CREATE VIEW departments_agt AS
    SELECT tlkpdept.deptcode, tlkpdept.dept, tlkpdept.dept_short, tlkpdept.grp, tlkpdept.inst, tlkpdept.pi, tlkpdept.link, tlkpdept.prog, tlkpdept.color_wkday_day AS color FROM tlkpdept WHERE (tlkpdept.ismain AND tlkpdept.iscurrent) ORDER BY tlkpdept.inst DESC, tlkpdept.prog, tlkpdept.pi DESC;


--
-- Name: tblsched; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tblsched (
    schedid integer DEFAULT nextval(('"tblsched_schedid_seq"'::text)::regclass) NOT NULL,
    scannercode character varying(5) NOT NULL,
    scheddate date NOT NULL,
    scheddow integer NOT NULL,
    schedhour integer NOT NULL,
    deptcode character varying(10) NOT NULL,
    researchercode character varying(15),
    time_used boolean,
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone,
    chg_by character varying(30) DEFAULT "current_user"(),
    billdeptcode character varying(10),
    templateid integer,
    post_on timestamp without time zone,
    orig_deptcode character varying(10),
    orig_instcode character varying(5),
    CONSTRAINT tblsched_scheddow CHECK (((scheddow >= 0) AND (scheddow <= 6))),
    CONSTRAINT tblsched_schedhour CHECK (((schedhour >= 0) AND (schedhour <= 23)))
);


--
-- Name: TABLE tblsched; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tblsched IS 'Schedule assignments';


--
-- Name: tlkpresearcher; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tlkpresearcher (
    researchercode character varying(15) NOT NULL,
    lname character varying(20) NOT NULL,
    fname character varying(20) NOT NULL,
    dept_code character varying(10),
    researchershort character varying(15) NOT NULL,
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone NOT NULL,
    chg_by character varying(30) DEFAULT "current_user"() NOT NULL,
    lose_to character varying(15)
);


--
-- Name: TABLE tlkpresearcher; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tlkpresearcher IS 'List of researchers';


--
-- Name: COLUMN tlkpresearcher.lose_to; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON COLUMN tlkpresearcher.lose_to IS 'Researcher code this loses to after reservation period';


--
-- Name: schedule; Type: VIEW; Schema: public; Owner: jburton
--

CREATE VIEW schedule AS
    SELECT s.schedid, s.scannercode, s.deptcode, d.dept_short, d.grp, s.scheddate, s.schedhour, r.researchercode, r.researchershort, d.color_wkday_day AS color, ((d.dept_short)::text || CASE WHEN (r.researchershort IS NULL) THEN ''::text ELSE ((' ('::text || (r.researchershort)::text) || ')'::text) END) AS label, s.time_used, s.templateid FROM ((tblsched s JOIN tlkpdept d USING (deptcode)) LEFT JOIN tlkpresearcher r USING (researchercode)) ORDER BY s.scheddate, s.schedhour, s.scannercode;


--
-- Name: schedule_agt; Type: VIEW; Schema: public; Owner: adamt
--

CREATE VIEW schedule_agt AS
    SELECT s.schedid, s.scannercode, s.deptcode, d.dept_short, d.grp, s.scheddate, s.schedhour, r.researchercode, s.billdeptcode, d.color_wkday_day AS color, ((d.dept_short)::text || (CASE WHEN (((((('('::character varying)::text || (r.fname)::text) || (' '::character varying)::text) || (r.lname)::text) || (')'::character varying)::text) IS NOT NULL) THEN (((((('('::character varying)::text || (r.fname)::text) || (' '::character varying)::text) || (r.lname)::text) || (')'::character varying)::text))::character varying WHEN ('' IS NOT NULL) THEN ''::character varying ELSE NULL::character varying END)::text) AS label, s.time_used FROM ((tblsched s JOIN tlkpdept d USING (deptcode)) LEFT JOIN tlkpresearcher r USING (researchercode)) ORDER BY s.scheddate, s.schedhour, s.scannercode;


--
-- Name: tblsched_schedid_seq; Type: SEQUENCE; Schema: public; Owner: jburton
--

CREATE SEQUENCE tblsched_schedid_seq
    INCREMENT BY 1
    MAXVALUE 2147483647
    NO MINVALUE
    CACHE 1;


--
-- Name: tbltemplate; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tbltemplate (
    templateid integer DEFAULT nextval(('"tbltemplate_templateid_seq"'::text)::regclass) NOT NULL,
    scannercode character varying(5) NOT NULL,
    dow integer NOT NULL,
    "hour" integer NOT NULL,
    deptcode character varying(10) NOT NULL,
    researchercode character varying(15),
    templatecode character varying(1) NOT NULL,
    instcode character varying(5),
    CONSTRAINT tbltemplate_dow CHECK (((dow >= 0) AND (dow <= 6))),
    CONSTRAINT tbltemplate_hour CHECK ((("hour" >= 0) AND ("hour" <= 23)))
);


--
-- Name: TABLE tbltemplate; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tbltemplate IS 'Templated times for scanner use';


--
-- Name: tbltemplate_templateid_seq; Type: SEQUENCE; Schema: public; Owner: jburton
--

CREATE SEQUENCE tbltemplate_templateid_seq
    INCREMENT BY 1
    MAXVALUE 2147483647
    NO MINVALUE
    CACHE 1;


--
-- Name: tbltemplates; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tbltemplates (
    templatecode character varying(1) NOT NULL,
    scannercode character varying(5) NOT NULL,
    "template" character varying(25),
    comments text,
    hidden boolean DEFAULT false
);


--
-- Name: TABLE tbltemplates; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tbltemplates IS 'List of scanner templates';


SET default_with_oids = false;

--
-- Name: technicalscans; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE technicalscans (
    tsid serial NOT NULL,
    subject character varying(50) NOT NULL,
    scantime timestamp without time zone NOT NULL,
    scannercode character varying(10) NOT NULL,
    deptcode character varying(10) NOT NULL,
    comments text,
    fullname character varying(50)
);


--
-- Name: temp_timelapse; Type: TABLE; Schema: public; Owner: zope; Tablespace: 
--

CREATE TABLE temp_timelapse (
    deptcode_old character varying(10),
    dept character varying(75),
    schedtime timestamp without time zone,
    posttime timestamp without time zone,
    scanner character varying(25),
    scannercode character varying(5),
    diff double precision
);


SET default_with_oids = false;

--
-- Name: tlkpinst; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tlkpinst (
    instcode character varying(5) NOT NULL,
    instshort character varying(10) NOT NULL,
    inst character varying(20) NOT NULL
);


--
-- Name: template; Type: VIEW; Schema: public; Owner: jburton
--

CREATE VIEW "template" AS
    SELECT t.templateid, t.templatecode, t.scannercode, t.deptcode, d.dept_short, d.grp, t.dow, t."hour", t.researchercode, r.researchershort, d.color_wkday_day AS color, (((d.dept_short)::text || CASE WHEN (r.researchershort IS NULL) THEN ''::text ELSE ((' ('::text || (r.researchershort)::text) || ')'::text) END) || CASE WHEN (i.instshort IS NULL) THEN ''::text ELSE ((' ['::text || (i.instshort)::text) || ']'::text) END) AS label, t.instcode FROM (((tbltemplate t JOIN tlkpdept d USING (deptcode)) LEFT JOIN tlkpresearcher r USING (researchercode)) LEFT JOIN tlkpinst i USING (instcode)) ORDER BY t.dow, t."hour", t.scannercode, t.templatecode;


--
-- Name: tlkpscanner; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tlkpscanner (
    scannercode character varying(5) NOT NULL,
    scanner character varying(25) NOT NULL,
    descrip text,
    mailinglist character varying(50),
    active boolean DEFAULT true
);


--
-- Name: TABLE tlkpscanner; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tlkpscanner IS 'List of scanners';


--
-- Name: tlogresearcher; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tlogresearcher (
    logid serial NOT NULL,
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
-- Name: tlogsched; Type: TABLE; Schema: public; Owner: jburton; Tablespace: 
--

CREATE TABLE tlogsched (
    logid serial NOT NULL,
    schedid integer,
    scannercode character varying(5),
    scheddate date,
    schedhour integer,
    deptcode character varying(10),
    researchercode character varying(15),
    time_used boolean,
    scannercode_old character varying(5),
    scheddate_old date,
    schedhour_old integer,
    deptcode_old character varying(10),
    researchercode_old character varying(15),
    time_used_old boolean,
    chg_at timestamp without time zone DEFAULT ('now'::text)::timestamp(6) with time zone,
    chg_by character varying(30)
);


--
-- Name: TABLE tlogsched; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON TABLE tlogsched IS 'Logging of changes. DOES NOT USE referential integrity!';


--
-- Name: vlogsched; Type: VIEW; Schema: public; Owner: jburton
--

CREATE VIEW vlogsched AS
    SELECT tlogsched.logid, tlogsched.schedid, tlogsched.scannercode, tlogsched.scheddate, tlogsched.schedhour, tlogsched.deptcode, tlogsched.researchercode, tlogsched.time_used, tlogsched.scannercode_old, tlogsched.scheddate_old, tlogsched.schedhour_old, tlogsched.deptcode_old, tlogsched.researchercode_old, tlogsched.time_used_old, tlogsched.chg_at, tlogsched.chg_by, (tlogsched.chg_at)::date AS chg_date, to_char(tlogsched.chg_at, 'FMMM/FMDD FMHH12:MIam'::text) AS chg_datetime FROM tlogsched;


--
-- Name: VIEW vlogsched; Type: COMMENT; Schema: public; Owner: jburton
--

COMMENT ON VIEW vlogsched IS 'Friendly view of loggig of changes';


--
-- Name: vlogsched_auditlapse; Type: VIEW; Schema: public; Owner: jburton
--

CREATE VIEW vlogsched_auditlapse AS
    SELECT l.deptcode_old AS deptcode, l.scheddate, l.schedhour, (l.scheddate + (((l.schedhour)::text || ' hours'::text))::interval) AS schedtime, l.chg_at AS posttime, l.scannercode, ((date_part('epoch'::text, (l.chg_at - (l.scheddate + (((l.schedhour)::text || ' hours'::text))::interval))) / (60)::double precision) / (60)::double precision) AS diff, CASE WHEN (((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) AND ((l.schedhour >= 8) AND (l.schedhour <= 17))) THEN 'wdp'::text WHEN ((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) THEN 'wdn'::text WHEN ((l.schedhour >= 8) AND (l.schedhour <= 17)) THEN 'wep'::text ELSE 'wen'::text END AS slottype FROM tlogsched l WHERE (((l.deptcode)::text = 'post'::text) AND ((l.deptcode_old)::text <> 'post'::text));


--
-- Name: vtblsched_audit; Type: VIEW; Schema: public; Owner: jburton
--

CREATE VIEW vtblsched_audit AS
    SELECT l.deptcode, l.scheddate, l.schedhour, l.scannercode, CASE WHEN l.time_used THEN 1 ELSE 0 END AS used, CASE WHEN ((((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) AND (l.schedhour >= 8)) AND (l.schedhour <= 17)) THEN 'wdp'::text WHEN ((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) THEN 'wdn'::text WHEN ((l.schedhour >= 8) AND (l.schedhour <= 17)) THEN 'wep'::text ELSE 'wen'::text END AS slottype FROM tblsched l WHERE ((((l.deptcode)::text <> ''::text) AND (l.time_used IS NOT NULL)) AND ((l.deptcode)::text <> 'post'::text));


--
-- Name: vtblsched_audit_alloc; Type: VIEW; Schema: public; Owner: apache
--

CREATE VIEW vtblsched_audit_alloc AS
    SELECT l.deptcode, l.orig_deptcode, l.scheddate, l.schedhour, l.scannercode, CASE WHEN l.time_used THEN 1 WHEN (l.time_used IS NULL) THEN 1 ELSE 0 END AS used, CASE WHEN ((((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) AND (l.schedhour >= 8)) AND (l.schedhour <= 17)) THEN 'wdp'::text WHEN ((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) THEN 'wdn'::text WHEN ((l.schedhour >= 8) AND (l.schedhour <= 17)) THEN 'wep'::text ELSE 'wen'::text END AS slottype FROM tblsched l WHERE (((l.deptcode)::text <> ''::text) AND ((l.deptcode)::text <> 'post'::text));


--
-- Name: vtblsched_audit_total; Type: VIEW; Schema: public; Owner: apache
--

CREATE VIEW vtblsched_audit_total AS
    SELECT l.deptcode, l.orig_deptcode, l.scheddate, l.schedhour, l.scannercode, CASE WHEN l.time_used THEN 1 WHEN (l.time_used IS NULL) THEN 1 ELSE 0 END AS used, CASE WHEN ((((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) AND (l.schedhour >= 8)) AND (l.schedhour <= 17)) THEN 'wdp'::text WHEN ((date_part('dow'::text, l.scheddate) >= (1)::double precision) AND (date_part('dow'::text, l.scheddate) <= (5)::double precision)) THEN 'wdn'::text WHEN ((l.schedhour >= 8) AND (l.schedhour <= 17)) THEN 'wep'::text ELSE 'wen'::text END AS slottype FROM tblsched l;


--
-- Name: VIEW vtblsched_audit_total; Type: COMMENT; Schema: public; Owner: apache
--

COMMENT ON VIEW vtblsched_audit_total IS 'Used to determine total allocated time by group';


--
-- Name: tblsched_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tblsched
    ADD CONSTRAINT tblsched_pkey PRIMARY KEY (schedid);


--
-- Name: tbltemplate_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_pkey PRIMARY KEY (templateid);


--
-- Name: tbltemplate_scannercode_key1; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_scannercode_key1 UNIQUE (scannercode, templatecode, dow, "hour");


--
-- Name: tbltemplates_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tbltemplates
    ADD CONSTRAINT tbltemplates_pkey PRIMARY KEY (templatecode, scannercode);


--
-- Name: technicalscans_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY technicalscans
    ADD CONSTRAINT technicalscans_pkey PRIMARY KEY (tsid);


--
-- Name: technicalscans_scantime_key; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY technicalscans
    ADD CONSTRAINT technicalscans_scantime_key UNIQUE (scantime, scannercode);


--
-- Name: tlkpdept_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlkpdept
    ADD CONSTRAINT tlkpdept_pkey PRIMARY KEY (deptcode);


--
-- Name: tlkpinst_instshort_key; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlkpinst
    ADD CONSTRAINT tlkpinst_instshort_key UNIQUE (instshort);


--
-- Name: tlkpinst_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlkpinst
    ADD CONSTRAINT tlkpinst_pkey PRIMARY KEY (instcode);


--
-- Name: tlkpresearcher_dept_code_key; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlkpresearcher
    ADD CONSTRAINT tlkpresearcher_dept_code_key UNIQUE (dept_code, researchershort);


--
-- Name: tlkpresearcher_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlkpresearcher
    ADD CONSTRAINT tlkpresearcher_pkey PRIMARY KEY (researchercode);


--
-- Name: tlkpscanner_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlkpscanner
    ADD CONSTRAINT tlkpscanner_pkey PRIMARY KEY (scannercode);


--
-- Name: tlogresearcher_pkey; Type: CONSTRAINT; Schema: public; Owner: jburton; Tablespace: 
--

ALTER TABLE ONLY tlogresearcher
    ADD CONSTRAINT tlogresearcher_pkey PRIMARY KEY (logid);


--
-- Name: scann_template; Type: INDEX; Schema: public; Owner: jburton; Tablespace: 
--

CREATE INDEX scann_template ON tbltemplates USING btree (scannercode, templatecode);

ALTER TABLE tbltemplates CLUSTER ON scann_template;


--
-- Name: tblsched_scannercode_key; Type: INDEX; Schema: public; Owner: jburton; Tablespace: 
--

CREATE UNIQUE INDEX tblsched_scannercode_key ON tblsched USING btree (scannercode, scheddate, schedhour);


--
-- Name: tbltemplate_scannercode_key; Type: INDEX; Schema: public; Owner: jburton; Tablespace: 
--

CREATE INDEX tbltemplate_scannercode_key ON tbltemplate USING btree (scannercode, templatecode, dow, "hour");


--
-- Name: tlkpdept_dept_key; Type: INDEX; Schema: public; Owner: jburton; Tablespace: 
--

CREATE UNIQUE INDEX tlkpdept_dept_key ON tlkpdept USING btree (dept);


--
-- Name: tlkpdept_dept_short_key; Type: INDEX; Schema: public; Owner: jburton; Tablespace: 
--

CREATE UNIQUE INDEX tlkpdept_dept_short_key ON tlkpdept USING btree (dept_short);


--
-- Name: tlkpscanner_scanner_key; Type: INDEX; Schema: public; Owner: jburton; Tablespace: 
--

CREATE UNIQUE INDEX tlkpscanner_scanner_key ON tlkpscanner USING btree (scanner);


--
-- Name: tblsched_ins; Type: RULE; Schema: public; Owner: jburton
--

CREATE RULE tblsched_ins AS ON INSERT TO tblsched DO INSERT INTO tlogsched (schedid, scannercode, scheddate, schedhour, deptcode, researchercode, time_used, chg_by) VALUES (new.schedid, new.scannercode, new.scheddate, new.schedhour, new.deptcode, new.researchercode, new.time_used, new.chg_by);


--
-- Name: tblsched_updateon; Type: RULE; Schema: public; Owner: jburton
--

CREATE RULE tblsched_updateon AS ON UPDATE TO tblsched DO INSERT INTO tlogsched (schedid, scannercode, scheddate, schedhour, deptcode, researchercode, time_used, scannercode_old, scheddate_old, schedhour_old, deptcode_old, researchercode_old, time_used_old, chg_at, chg_by) VALUES (new.schedid, new.scannercode, new.scheddate, new.schedhour, new.deptcode, new.researchercode, new.time_used, old.scannercode, old.scheddate, old.schedhour, old.deptcode, old.researchercode, old.time_used, ('now'::text)::timestamp(6) with time zone, new.chg_by);


--
-- Name: template_fill; Type: RULE; Schema: public; Owner: jburton
--

CREATE RULE template_fill AS ON INSERT TO tbltemplates DO SELECT template_default_fill(new.scannercode, new.templatecode) AS template_default_fill;


--
-- Name: tlkpresearcher_del; Type: RULE; Schema: public; Owner: jburton
--

CREATE RULE tlkpresearcher_del AS ON DELETE TO tlkpresearcher DO INSERT INTO tlogresearcher (chg_at, chg_by, researchercode_old, lname_old, fname_old, researchershort_old, dept_code__old) VALUES (('now'::text)::timestamp(6) with time zone, "current_user"(), old.researchercode, old.lname, old.fname, old.researchershort, old.dept_code);


--
-- Name: tlkpresearcher_ins; Type: RULE; Schema: public; Owner: jburton
--

CREATE RULE tlkpresearcher_ins AS ON INSERT TO tlkpresearcher DO INSERT INTO tlogresearcher (researchercode, lname, fname, researchershort, dept_code, chg_at, chg_by) VALUES (new.researchercode, new.lname, new.fname, new.researchershort, new.dept_code, ('now'::text)::timestamp(6) with time zone, "current_user"());


--
-- Name: tlkpresearcher_upd; Type: RULE; Schema: public; Owner: jburton
--

CREATE RULE tlkpresearcher_upd AS ON UPDATE TO tlkpresearcher DO INSERT INTO tlogresearcher (researchercode, lname, fname, researchershort, dept_code, chg_at, chg_by, researchercode_old, lname_old, fname_old, researchershort_old, dept_code__old) VALUES (new.researchercode, new.lname, new.fname, new.researchershort, new.dept_code, ('now'::text)::timestamp(6) with time zone, "current_user"(), old.researchercode, old.lname, old.fname, old.researchershort, old.dept_code);


--
-- Name: tblsched_billdeptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tblsched
    ADD CONSTRAINT tblsched_billdeptcode_fkey FOREIGN KEY (billdeptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE;


--
-- Name: tblsched_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tblsched
    ADD CONSTRAINT tblsched_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE;


--
-- Name: tbltemplate_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE;


--
-- Name: tbltemplate_instcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_instcode_fkey FOREIGN KEY (instcode) REFERENCES tlkpinst(instcode);


--
-- Name: tbltemplate_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tbltemplate
    ADD CONSTRAINT tbltemplate_scannercode_fkey FOREIGN KEY (scannercode, templatecode) REFERENCES tbltemplates(scannercode, templatecode) ON UPDATE CASCADE DEFERRABLE;


--
-- Name: tbltemplates_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tbltemplates
    ADD CONSTRAINT tbltemplates_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES tlkpscanner(scannercode) ON UPDATE CASCADE DEFERRABLE;


--
-- Name: technicalscans_deptcode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY technicalscans
    ADD CONSTRAINT technicalscans_deptcode_fkey FOREIGN KEY (deptcode) REFERENCES tlkpdept(deptcode);


--
-- Name: technicalscans_scannercode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY technicalscans
    ADD CONSTRAINT technicalscans_scannercode_fkey FOREIGN KEY (scannercode) REFERENCES tlkpscanner(scannercode);


--
-- Name: tlkpresearcher_dept_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tlkpresearcher
    ADD CONSTRAINT tlkpresearcher_dept_code_fkey FOREIGN KEY (dept_code) REFERENCES tlkpdept(deptcode) ON UPDATE CASCADE DEFERRABLE;


--
-- Name: tlkpresearcher_lose_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: jburton
--

ALTER TABLE ONLY tlkpresearcher
    ADD CONSTRAINT tlkpresearcher_lose_to_fkey FOREIGN KEY (lose_to) REFERENCES tlkpresearcher(researchercode);


--
-- PostgreSQL database dump complete
--

