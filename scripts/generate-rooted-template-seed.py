#!/usr/bin/env python3
"""Generate a rooted legacy template seed from a bootstrapped old database.

The generated SQL is intended for the early import stage (`sql/003-import-data.sql`)
of the current app's migration chain. It can emit either pre-018 or post-018
researcher identifiers so the current chain can be verified against both data
stages.

The template tables are emitted in explicit data-dump shape (`tbltemplates`
plus `tbltemplate` rows) rather than relying on the old `template_fill` rule.
`sql/000-init.sh` loads `003-import-data.sql` under
`session_replication_role = replica`, which disables that rule.
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

DEFAULT_DATABASE = "fmrif_scheduler_oldcompat"
LEGACY_OLD_SUFFIX = "[OLD]"
LEGACY_NONE_GROUP = "(none)"
NULL_SENTINEL = "__CODEX_NULL__"


@dataclass(frozen=True)
class TemplateKey:
    device: str
    template: str


DEFAULT_SUBSET = (
    TemplateKey("d", "a"),
    TemplateKey("d", "i"),
    TemplateKey("d", "j"),
    TemplateKey("test", "t"),
)
SUPPORTED_RESEARCHER_STAGES = ("pre-018", "post-018")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Bootstrapped old database to read from (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--template",
        action="append",
        default=[],
        metavar="DEVICE:TEMPLATE",
        help="Subset template to export; repeatable. Defaults to a rooted legacy subset.",
    )
    parser.add_argument(
        "--researcher-stage",
        choices=SUPPORTED_RESEARCHER_STAGES,
        default="pre-018",
        help=(
            "Whether emitted researcher codes should be normalized back to pre-018 "
            "form or preserved in post-018 [OLD] form (default: pre-018)."
        ),
    )
    return parser.parse_args()


def parse_template_key(value: str) -> TemplateKey:
    try:
        device, template = value.split(":", 1)
    except ValueError as exc:
        raise SystemExit(
            f"Invalid --template value: {value!r}; expected DEVICE:TEMPLATE"
        ) from exc
    return TemplateKey(device, template)


def run_query(database: str, sql: str) -> list[tuple[str, ...]]:
    proc = subprocess.run(
        [
            "psql",
            "-X",
            "-A",
            "-t",
            "-F",
            "\t",
            "-P",
            f"null={NULL_SENTINEL}",
            "-d",
            database,
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[str, ...]] = []
    for raw_line in proc.stdout.splitlines():
        if (
            not raw_line
            or raw_line == "COPY"
            or re.fullmatch(r"\(\d+ rows?\)", raw_line)
        ):
            continue
        rows.append(
            tuple(
                None if value == NULL_SENTINEL else value
                for value in raw_line.split("\t")
            )
        )
    return rows


def sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def strip_old_suffix(value: str | None) -> str | None:
    if value is None:
        return None
    if value.endswith(LEGACY_OLD_SUFFIX):
        return value[: -len(LEGACY_OLD_SUFFIX)]
    return value


def normalize_researchercode(value: str | None, researcher_stage: str) -> str | None:
    if researcher_stage == "pre-018":
        return strip_old_suffix(value)
    if researcher_stage == "post-018":
        return value
    raise ValueError(f"Unsupported researcher stage: {researcher_stage}")


def template_predicate(keys: Iterable[TemplateKey], table_alias: str = "") -> str:
    prefix = f"{table_alias}." if table_alias else ""
    pairs = ", ".join(
        f"({sql_literal(k.device)}, {sql_literal(k.template)})" for k in keys
    )
    return f"({prefix}scannercode, {prefix}templatecode) in ({pairs})"


def ordered_unique(
    rows: Iterable[tuple[str, ...]], key_index: int = 0
) -> list[tuple[str, ...]]:
    data: "OrderedDict[str, tuple[str, ...]]" = OrderedDict()
    for row in rows:
        data.setdefault(row[key_index], row)
    return list(data.values())


def emit_insert(
    table: str, columns: list[str], rows: list[tuple[str | None, ...]]
) -> str:
    if not rows:
        return f"-- No rows selected for {table}.\n"
    lines = [f"INSERT INTO {table} ({', '.join(columns)}) VALUES"]
    rendered_rows = []
    for row in rows:
        rendered = ", ".join(sql_literal(value) for value in row)
        rendered_rows.append(f"({rendered})")
    lines.append(",\n".join(rendered_rows) + ";")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    subset = tuple(parse_template_key(v) for v in args.template) or DEFAULT_SUBSET
    predicate = template_predicate(subset)

    slot_counts = run_query(
        args.database,
        f"""
        with per_template as (
            select scannercode, templatecode, count(*) as slot_count
            from tbltemplate
            where {predicate}
            group by 1, 2
        )
        select scannercode, templatecode, slot_count
        from per_template
        order by scannercode, templatecode;
        """,
    )
    if not slot_counts:
        raise SystemExit("No templates matched the requested subset.")
    bad_counts = [row for row in slot_counts if row[2] != "168"]
    if bad_counts:
        raise SystemExit(
            f"Expected full-grid templates only, found non-168 counts: {bad_counts}"
        )

    template_rows = run_query(
        args.database,
        f"""
        select
            scannercode,
            templatecode,
            replace(replace(template, E'\\n', ' '), E'\\t', ' '),
            replace(replace(comments, E'\\n', ' '), E'\\t', ' '),
            case when hidden then 'true' else 'false' end
        from tbltemplates
        where {predicate}
        order by scannercode, templatecode;
        """,
    )
    scanner_rows = run_query(
        args.database,
        f"""
        select distinct s.scannercode, s.scanner, s.descrip, s.mailinglist, case when s.active then 'true' else 'false' end
        from tlkpscanner s
        join tbltemplates t using (scannercode)
        where {predicate}
        order by s.scannercode;
        """,
    )
    inst_rows = run_query(
        args.database,
        f"""
        with needed_insts as (
            select distinct inst as instcode
            from tlkpdept
            where deptcode in (
                select distinct deptcode
                from tbltemplate
                where {predicate}
            )
              and inst is not null
              and inst <> ''
            union
            select distinct instcode
            from tbltemplate
            where {predicate}
              and instcode is not null
              and instcode <> ''
        )
        select instcode, instcode as instshort, inst
        from tlkpinst
        where instcode in (select instcode from needed_insts)
        order by instcode;
        """,
    )
    dept_rows = run_query(
        args.database,
        f"""
        with needed_depts as (
            select distinct deptcode
            from tbltemplate
            where {predicate}
            union
            select distinct dept_code
            from tlkpresearcher
            where researchercode in (
                select distinct researchercode
                from tbltemplate
                where {predicate}
                  and researchercode is not null
            )
        )
        select deptcode, dept, dept_short, grp, replace(color, '#', ''), null, null, null,
               case when ismain then 'true' else 'false' end,
               case when iscurrent then 'true' else 'false' end, inst, prog, link, pi, lose_to, email
        from tlkpdept
        where deptcode in (select deptcode from needed_depts)
        order by deptcode;
        """,
    )
    needed_researchers = run_query(
        args.database,
        f"""
        select distinct researchercode
        from tbltemplate
        where {predicate}
          and researchercode is not null
        order by researchercode;
        """,
    )
    researcher_lookup = {
        row[0]: row
        for row in run_query(
            args.database,
            f"""
            select researchercode, lname, fname, dept_code, researchershort, chg_at::text, chg_by, lose_to
            from tlkpresearcher
            where researchercode in (
                select distinct researchercode
                from tbltemplate
                where {predicate}
                  and researchercode is not null
            )
            order by researchercode;
            """,
        )
    }
    template_cells = run_query(
        args.database,
        f"""
        select templateid::text, scannercode, dow::text, hour::text, deptcode, researchercode, templatecode, instcode
        from tbltemplate
        where {predicate}
        order by scannercode, templatecode, dow, hour, templateid;
        """,
    )

    transformed_researchers: list[tuple[str | None, ...]] = []
    seen_bases: set[str] = set()
    for (code,) in needed_researchers:
        source = researcher_lookup[code]
        emitted_code = normalize_researchercode(source[0], args.researcher_stage)
        if emitted_code in seen_bases:
            continue
        seen_bases.add(emitted_code)
        transformed_researchers.append(
            (
                emitted_code,
                source[1],
                source[2],
                source[3],
                source[4],
                source[5],
                source[6],
                source[7],
            )
        )

    transformed_cells = []
    for (
        templateid,
        scannercode,
        dow,
        hour,
        deptcode,
        researchercode,
        templatecode,
        instcode,
    ) in template_cells:
        transformed_cells.append(
            (
                templateid,
                scannercode,
                dow,
                hour,
                deptcode,
                normalize_researchercode(researchercode, args.researcher_stage),
                templatecode,
                instcode,
            )
        )

    header = io.StringIO()
    header.write("-- Generated by scripts/generate-rooted-template-seed.py\n")
    header.write(f"-- Source database: {args.database}\n")
    header.write(f"-- Researcher stage: {args.researcher_stage}\n")
    header.write(
        "-- Selected templates: "
        + ", ".join(f"{key.device}/{key.template}" for key in subset)
        + "\n\n"
    )

    body = io.StringIO()
    body.write(
        emit_insert(
            "tlkpinst",
            ["instcode", "instshort", "inst"],
            inst_rows,
        )
    )
    body.write("\n")
    body.write(
        emit_insert(
            "tlkpscanner",
            ["scannercode", "scanner", "descrip", "mailinglist", "active"],
            scanner_rows,
        )
    )
    body.write("\n")
    body.write(
        emit_insert(
            "tlkpdept",
            [
                "deptcode",
                "dept",
                "dept_short",
                "grp",
                "color_wkday_day",
                "color_wkday_eve",
                "color_wkend_day",
                "color_wkend_eve",
                "ismain",
                "iscurrent",
                "inst",
                "prog",
                "link",
                "pi",
                "lose_to",
                "email",
            ],
            dept_rows,
        )
    )
    body.write("\n")
    body.write(
        emit_insert(
            "tlkpresearcher",
            [
                "researchercode",
                "lname",
                "fname",
                "dept_code",
                "researchershort",
                "chg_at",
                "chg_by",
                "lose_to",
            ],
            transformed_researchers,
        )
    )
    body.write("\n")
    body.write(
        emit_insert(
            "tbltemplates",
            ["templatecode", "scannercode", "template", "comments", "hidden"],
            [(row[1], row[0], row[2], row[3], row[4]) for row in template_rows],
        )
    )
    body.write("\n")
    body.write(
        emit_insert(
            "tbltemplate",
            [
                "templateid",
                "scannercode",
                "dow",
                "hour",
                "deptcode",
                "researchercode",
                "templatecode",
                "instcode",
            ],
            transformed_cells,
        )
    )

    sys.stdout.write(header.getvalue())
    sys.stdout.write(body.getvalue())


if __name__ == "__main__":
    main()
