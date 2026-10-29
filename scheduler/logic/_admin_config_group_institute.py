"""Group-institute mapping parsing, scanning, and export helpers."""

from __future__ import annotations

import datetime
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict

from sqlalchemy import select

from scheduler import model

from ._admin_config_settings import (
    ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING,
    GROUP_INSTITUTE_HISTORY_WINDOW_YEARS,
    _normalize_text,
    get_admin_setting,
    normalize_group_institute_history_window_years,
    set_admin_setting,
)


class CanonicalInstituteConfig(TypedDict):
    label: str
    kind: str
    active: bool


class GroupInstituteException(TypedDict):
    group: str
    device: str
    template: str
    raw_institute: str
    canonical_institute: str
    reason: str


class GroupInstituteMapping(TypedDict):
    canonical_institutes: Dict[str, CanonicalInstituteConfig]
    raw_aliases: Dict[str, str]
    group_defaults: Dict[str, str]
    exceptions: List[GroupInstituteException]


class GroupInstituteIssueRow(TypedDict, total=False):
    label: str
    detail: str
    count: int


class GroupInstituteIssueSection(TypedDict):
    id: str
    title: str
    severity: str
    issue_count: int
    rows: List[GroupInstituteIssueRow]
    hidden_count: int


class MappingScanSummary(TypedDict):
    raw_institute_count: int
    raw_institutes: List[str]
    active_group_count: int
    groups_with_canonical_default_count: int
    template_entry_count: int
    canonical_institute_count: int


class HistoryScanSummary(TypedDict):
    window_years: int
    window_start: str
    window_end: str
    schedule_entry_count: int
    flagged_schedule_row_count: int
    issue_count: int


class GroupInstituteMappingScanResult(TypedDict):
    summary: MappingScanSummary
    sections: List[GroupInstituteIssueSection]


class GroupInstituteHistoryScanResult(TypedDict):
    summary: HistoryScanSummary
    sections: List[GroupInstituteIssueSection]


class RawInstituteStatus(TypedDict):
    label: str
    active: bool


class GroupInstituteScanContext(TypedDict):
    canonical: Dict[str, CanonicalInstituteConfig]
    inst_status: Dict[str, RawInstituteStatus]
    known_groups: set[str]
    active_group_rows: List[Tuple[str, str, bool, str]]
    group_expected_canonical: Dict[str, str]


_RECOMMENDED_NIH_ICS: Tuple[Tuple[str, str], ...] = (
    ("CC", "NIH Clinical Center"),
    ("CIT", "Center for Information Technology"),
    ("CSR", "Center for Scientific Review"),
    ("FIC", "Fogarty International Center"),
    ("NCATS", "National Center for Advancing Translational Sciences"),
    ("NCCIH", "National Center for Complementary and Integrative Health"),
    ("NCI", "National Cancer Institute"),
    ("NEI", "National Eye Institute"),
    ("NHGRI", "National Human Genome Research Institute"),
    ("NHLBI", "National Heart, Lung, and Blood Institute"),
    ("NIA", "National Institute on Aging"),
    ("NIAAA", "National Institute on Alcohol Abuse and Alcoholism"),
    ("NIAID", "National Institute of Allergy and Infectious Diseases"),
    ("NIAMS", "National Institute of Arthritis and Musculoskeletal and Skin Diseases"),
    ("NIBIB", "National Institute of Biomedical Imaging and Bioengineering"),
    (
        "NICHD",
        "Eunice Kennedy Shriver National Institute of Child Health and Human Development",
    ),
    ("NIDA", "National Institute on Drug Abuse"),
    ("NIDCD", "National Institute on Deafness and Other Communication Disorders"),
    ("NIDCR", "National Institute of Dental and Craniofacial Research"),
    ("NIDDK", "National Institute of Diabetes and Digestive and Kidney Diseases"),
    ("NIEHS", "National Institute of Environmental Health Sciences"),
    ("NIGMS", "National Institute of General Medical Sciences"),
    ("NIMH", "National Institute of Mental Health"),
    ("NIMHD", "National Institute on Minority Health and Health Disparities"),
    ("NINDS", "National Institute of Neurological Disorders and Stroke"),
    ("NINR", "National Institute of Nursing Research"),
    ("NLM", "National Library of Medicine"),
)

_RECOMMENDED_LOCAL_CANONICAL_INSTITUTES: Tuple[Tuple[str, str], ...] = (
    ("DEV", "Scanner Development"),
    ("MAINT", "Maintenance Time"),
    ("TRAIN", "Training"),
    ("NMRF", "NIH MRI Research Facility"),
)

_RECOMMENDED_RAW_ALIASES: Dict[str, str] = {
    "Clinical Center": "CC",
    "GE": "MAINT",
    "NCCAM": "NCCIH",
}


def _normalize_mapping_string(
    value: Any, *, field: str, allow_blank: bool = False
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not allow_blank and normalized == "":
        raise ValueError(f"{field} must not be empty")
    return normalized


def _empty_group_institute_mapping() -> GroupInstituteMapping:
    return {
        "canonical_institutes": {},
        "raw_aliases": {},
        "group_defaults": {},
        "exceptions": [],
    }


def recommended_group_institute_mapping() -> GroupInstituteMapping:
    canonical_institutes: Dict[str, CanonicalInstituteConfig] = {}
    for inst_id, label in _RECOMMENDED_NIH_ICS:
        canonical_institutes[inst_id] = {
            "label": label,
            "kind": "nih_ic",
            "active": True,
        }
    for inst_id, label in _RECOMMENDED_LOCAL_CANONICAL_INSTITUTES:
        canonical_institutes[inst_id] = {
            "label": label,
            "kind": "local_operational",
            "active": True,
        }
    return {
        "canonical_institutes": canonical_institutes,
        "raw_aliases": dict(_RECOMMENDED_RAW_ALIASES),
        "group_defaults": {},
        "exceptions": [],
    }


def _parse_group_institute_mapping_payload(raw: Any) -> GroupInstituteMapping:
    if not isinstance(raw, dict):
        raise ValueError("group institute mapping must be a JSON object")

    normalized = _empty_group_institute_mapping()

    canonical_raw = raw.get("canonical_institutes", {})
    if canonical_raw in (None, ""):
        canonical_raw = {}
    if not isinstance(canonical_raw, dict):
        raise ValueError("canonical_institutes must be a JSON object")
    canonical: Dict[str, CanonicalInstituteConfig] = {}
    for raw_key, raw_value in canonical_raw.items():
        canonical_id = _normalize_mapping_string(
            raw_key, field="canonical institute id"
        )
        if not isinstance(raw_value, dict):
            raise ValueError(
                f"canonical_institutes.{canonical_id} must be a JSON object"
            )
        label_value = raw_value.get("label", canonical_id)
        label = _normalize_mapping_string(
            label_value, field=f"canonical_institutes.{canonical_id}.label"
        )
        kind_value = raw_value.get("kind", "unknown")
        kind = _normalize_mapping_string(
            kind_value, field=f"canonical_institutes.{canonical_id}.kind"
        )
        active_value = raw_value.get("active", True)
        if not isinstance(active_value, bool):
            raise ValueError(
                f"canonical_institutes.{canonical_id}.active must be true or false"
            )
        canonical[canonical_id] = {
            "label": label,
            "kind": kind,
            "active": active_value,
        }
    normalized["canonical_institutes"] = canonical

    raw_aliases_raw = raw.get("raw_aliases", {})
    if raw_aliases_raw in (None, ""):
        raw_aliases_raw = {}
    if not isinstance(raw_aliases_raw, dict):
        raise ValueError("raw_aliases must be a JSON object")
    raw_aliases: Dict[str, str] = {}
    for raw_key, raw_value in raw_aliases_raw.items():
        alias = _normalize_mapping_string(raw_key, field="raw alias")
        canonical_id = _normalize_mapping_string(
            raw_value, field=f"raw_aliases.{alias}"
        )
        if canonical_id not in canonical:
            raise ValueError(
                f"raw_aliases.{alias} refers to unknown canonical institute "
                f"{canonical_id!r}"
            )
        raw_aliases[alias] = canonical_id
    normalized["raw_aliases"] = raw_aliases

    group_defaults_raw = raw.get("group_defaults", {})
    if group_defaults_raw in (None, ""):
        group_defaults_raw = {}
    if not isinstance(group_defaults_raw, dict):
        raise ValueError("group_defaults must be a JSON object")
    group_defaults: Dict[str, str] = {}
    for raw_key, raw_value in group_defaults_raw.items():
        group_id = _normalize_mapping_string(raw_key, field="group default key")
        canonical_id = _normalize_mapping_string(
            raw_value, field=f"group_defaults.{group_id}"
        )
        if canonical_id not in canonical:
            raise ValueError(
                f"group_defaults.{group_id} refers to unknown canonical institute "
                f"{canonical_id!r}"
            )
        group_defaults[group_id] = canonical_id
    normalized["group_defaults"] = group_defaults

    exceptions_raw = raw.get("exceptions", [])
    if exceptions_raw in (None, ""):
        exceptions_raw = []
    if not isinstance(exceptions_raw, list):
        raise ValueError("exceptions must be a JSON array")
    exceptions: List[GroupInstituteException] = []
    for index, item in enumerate(exceptions_raw):
        if not isinstance(item, dict):
            raise ValueError(f"exceptions[{index}] must be a JSON object")
        normalized_item: GroupInstituteException = {
            "group": _normalize_text(item.get("group")),
            "device": _normalize_text(item.get("device")),
            "template": _normalize_text(item.get("template")),
            "raw_institute": _normalize_text(item.get("raw_institute")),
            "canonical_institute": _normalize_text(item.get("canonical_institute")),
            "reason": _normalize_text(item.get("reason")),
        }
        if normalized_item["canonical_institute"] != "":
            canonical_id = normalized_item["canonical_institute"]
            if canonical_id not in canonical:
                raise ValueError(
                    f"exceptions[{index}].canonical_institute refers to unknown "
                    f"canonical institute {canonical_id!r}"
                )
        if normalized_item["reason"] == "":
            raise ValueError(f"exceptions[{index}].reason must not be empty")
        if not any(
            normalized_item[key] != ""
            for key in (
                "group",
                "device",
                "template",
                "raw_institute",
                "canonical_institute",
            )
        ):
            raise ValueError(
                f"exceptions[{index}] must include at least one matching field"
            )
        exceptions.append(normalized_item)
    normalized["exceptions"] = exceptions

    return normalized


def parse_admin_group_institute_mapping(raw_text: str) -> GroupInstituteMapping:
    payload = _normalize_text(raw_text)
    if payload == "":
        return _empty_group_institute_mapping()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as ex:
        raise ValueError(f"group institute mapping must be valid JSON: {ex}") from ex
    return _parse_group_institute_mapping_payload(parsed)


def get_admin_group_institute_mapping() -> GroupInstituteMapping:
    raw = get_admin_setting(ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING, "")
    if _normalize_text(raw) == "":
        return recommended_group_institute_mapping()
    try:
        return parse_admin_group_institute_mapping(raw)
    except ValueError:
        return _empty_group_institute_mapping()


def get_admin_group_institute_mapping_error() -> str:
    raw = get_admin_setting(ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING, "")
    if _normalize_text(raw) == "":
        return ""
    try:
        parse_admin_group_institute_mapping(raw)
    except ValueError as ex:
        return str(ex)
    return ""


def format_admin_group_institute_mapping_for_form() -> str:
    raw = get_admin_setting(ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING, "")
    if _normalize_text(raw) == "":
        return json.dumps(
            recommended_group_institute_mapping(), sort_keys=True, indent=2
        )
    try:
        parsed = parse_admin_group_institute_mapping(raw)
    except ValueError:
        return str(raw)
    return json.dumps(parsed, sort_keys=True, indent=2)


def admin_group_institute_mapping_uses_recommended_default() -> bool:
    raw = get_admin_setting(ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING, "")
    return _normalize_text(raw) == ""


def set_admin_group_institute_mapping(
    values: Dict[str, Any], *, updated_by: Optional[str] = None
) -> bool:
    normalized = _parse_group_institute_mapping_payload(values)
    return set_admin_setting(
        ADMIN_SETTING_KEY_GROUP_INSTITUTE_MAPPING,
        json.dumps(normalized, sort_keys=True, indent=2),
        updated_by=updated_by,
    )


def _resolve_canonical_institute(raw_value: str, mapping: GroupInstituteMapping) -> str:
    token = _normalize_text(raw_value)
    if token == "":
        return ""
    canonical = mapping.get("canonical_institutes", {})
    if token in canonical:
        return token
    raw_aliases = mapping.get("raw_aliases", {})
    return _normalize_text(raw_aliases.get(token))


def _group_institute_exception_matches(
    exception: GroupInstituteException,
    *,
    group: str,
    device: str,
    template: str,
    raw_institute: str,
    canonical_institute: str,
) -> bool:
    for key, actual in (
        ("group", group),
        ("device", device),
        ("template", template),
        ("raw_institute", raw_institute),
        ("canonical_institute", canonical_institute),
    ):
        expected = _normalize_text(exception.get(key))
        if expected != "" and expected != actual:
            return False
    return True


def _group_institute_scan_context(
    normalized_mapping: GroupInstituteMapping,
) -> GroupInstituteScanContext:
    canonical = normalized_mapping["canonical_institutes"]

    inst_rows = model.db.session.execute(
        select(model.Inst.id, model.Inst.label, model.Inst.active).order_by(
            model.Inst.id
        )
    ).all()
    inst_status: Dict[str, RawInstituteStatus] = {
        str(inst_id): {
            "label": _normalize_text(inst_label) or str(inst_id),
            "active": bool(active),
        }
        for inst_id, inst_label, active in inst_rows
    }

    group_rows = model.db.session.execute(
        select(
            model.Group.id,
            model.Group.label,
            model.Group.active,
            model.Group.inst,
        ).order_by(model.Group.id)
    ).all()
    known_groups = {str(group_id) for group_id, _, _, _ in group_rows}
    active_group_rows = [
        (
            str(group_id),
            _normalize_text(group_label),
            bool(active),
            _normalize_text(inst),
        )
        for group_id, group_label, active, inst in group_rows
        if bool(active) and _normalize_text(group_id) != ""
    ]
    group_expected_canonical = {
        group_id: (
            _normalize_text(normalized_mapping["group_defaults"].get(group_id))
            or _resolve_canonical_institute(group_inst, normalized_mapping)
        )
        for group_id, _, _, group_inst in active_group_rows
    }

    return {
        "canonical": canonical,
        "inst_status": inst_status,
        "known_groups": known_groups,
        "active_group_rows": active_group_rows,
        "group_expected_canonical": group_expected_canonical,
    }


def _build_issue_sections(
    issue_buckets: Dict[str, List[GroupInstituteIssueRow]],
    section_specs: Sequence[Tuple[str, str, str]],
    *,
    preview_limit: Optional[int] = 10,
) -> List[GroupInstituteIssueSection]:
    sections: List[GroupInstituteIssueSection] = []
    for section_id, title, severity in section_specs:
        items = issue_buckets.get(section_id, [])
        if not items:
            continue
        shown_items = items if preview_limit is None else items[: max(0, preview_limit)]
        sections.append(
            {
                "id": section_id,
                "title": title,
                "severity": severity,
                "issue_count": len(items),
                "rows": shown_items,
                "hidden_count": max(0, len(items) - len(shown_items)),
            }
        )
    return sections


def scan_admin_group_institute_mapping(
    mapping: Optional[Dict[str, Any]] = None,
    *,
    preview_limit: Optional[int] = 10,
) -> GroupInstituteMappingScanResult:
    normalized_mapping = (
        _parse_group_institute_mapping_payload(mapping)
        if isinstance(mapping, dict)
        else get_admin_group_institute_mapping()
    )
    context = _group_institute_scan_context(normalized_mapping)
    canonical = context["canonical"]
    inst_status = context["inst_status"]
    known_groups = context["known_groups"]
    active_group_rows = context["active_group_rows"]
    group_expected_canonical = context["group_expected_canonical"]

    template_rows = model.db.session.execute(
        select(
            model.TemplateEntry.device,
            model.TemplateEntry.template,
            model.TemplateEntry.group,
            model.TemplateEntry.inst,
        ).where(model.TemplateEntry.group.is_not(None))
    ).all()

    issue_buckets: Dict[str, List[GroupInstituteIssueRow]] = defaultdict(list)

    def add_issue(section_id: str, label: str, detail: str) -> None:
        issue_buckets[section_id].append({"label": label, "detail": detail})

    for raw_inst_id, data in inst_status.items():
        resolved = _resolve_canonical_institute(raw_inst_id, normalized_mapping)
        if resolved == "":
            add_issue(
                "unmapped-raw-institutes",
                raw_inst_id,
                f"Raw institute {raw_inst_id} ({data['label']}) is present in tlkpinst "
                "but does not resolve to any canonical institute.",
            )

    for group_id, group_label, _, group_inst in active_group_rows:
        if group_inst == "":
            add_issue(
                "groups-missing-default-institute",
                group_id,
                f"{group_label or group_id} has no raw default institute in tlkpdept.inst.",
            )
            continue
        inst_meta = inst_status.get(group_inst)
        if inst_meta is not None and not bool(inst_meta["active"]):
            add_issue(
                "groups-inactive-default-institute",
                group_id,
                f"{group_label or group_id} uses inactive institute {group_inst}.",
            )
        if group_expected_canonical.get(group_id, "") == "":
            add_issue(
                "groups-unmapped-default-institute",
                group_id,
                f"{group_label or group_id} uses raw institute {group_inst}, but that "
                "value does not resolve to a canonical institute.",
            )

    for group_id, canonical_id in sorted(normalized_mapping["group_defaults"].items()):
        if group_id not in known_groups:
            add_issue(
                "unknown-group-default-overrides",
                group_id,
                f"Mapping overrides {group_id} to canonical institute {canonical_id}, "
                "but that group is not present in this environment.",
            )

    raw_institutes_by_group: Dict[str, set[str]] = defaultdict(set)
    used_canonical_institutes = {
        canonical_id
        for canonical_id in normalized_mapping["group_defaults"].values()
        if canonical_id in canonical
    }
    used_canonical_institutes.update(
        canonical_id
        for canonical_id in normalized_mapping["raw_aliases"].values()
        if canonical_id in canonical
    )
    used_canonical_institutes.update(
        resolved
        for raw_inst_id in inst_status
        for resolved in [_resolve_canonical_institute(raw_inst_id, normalized_mapping)]
        if resolved != ""
    )

    for device_id, template_id, group_id, raw_inst in template_rows:
        group_key = _normalize_text(group_id)
        raw_institute = _normalize_text(raw_inst)
        if group_key == "":
            continue
        if raw_institute != "":
            raw_institutes_by_group[group_key].add(raw_institute)
        resolved_slot = _resolve_canonical_institute(raw_institute, normalized_mapping)
        if resolved_slot != "":
            used_canonical_institutes.add(resolved_slot)
        expected = group_expected_canonical.get(group_key, "")
        if raw_institute != "" and resolved_slot == "":
            add_issue(
                "template-unmapped-institutes",
                f"{device_id}:{template_id}:{group_key}",
                f"Template {template_id} on {device_id} uses raw institute "
                f"{raw_institute}, which does not resolve to a canonical institute.",
            )
            continue
        if expected == "" or raw_institute == "" or resolved_slot == "":
            continue
        if resolved_slot == expected:
            continue
        if any(
            _group_institute_exception_matches(
                exception,
                group=group_key,
                device=_normalize_text(device_id),
                template=_normalize_text(template_id),
                raw_institute=raw_institute,
                canonical_institute=resolved_slot,
            )
            for exception in normalized_mapping["exceptions"]
        ):
            continue
        add_issue(
            "template-default-mismatches",
            f"{device_id}:{template_id}:{group_key}",
            f"Template {template_id} on {device_id} resolves to {resolved_slot} "
            f"for group {group_key}, but the group default resolves to {expected}.",
        )

    for group_id, raw_institutes in sorted(raw_institutes_by_group.items()):
        if len(raw_institutes) > 1:
            add_issue(
                "groups-with-multiple-template-institutes",
                group_id,
                f"Templates currently use multiple raw institutes for {group_id}: "
                + ", ".join(sorted(raw_institutes)),
            )

    for canonical_id, config_value in sorted(canonical.items()):
        if canonical_id not in used_canonical_institutes:
            add_issue(
                "unused-canonical-institutes",
                canonical_id,
                f"{config_value['label']} is defined in the canonical mapping but is "
                "not currently referenced by group defaults, raw aliases, or templates "
                "in this environment.",
            )

    section_specs = (
        (
            "template-default-mismatches",
            "template/group canonical mismatches",
            "critical",
        ),
        (
            "groups-inactive-default-institute",
            "groups using inactive raw institutes",
            "critical",
        ),
        (
            "groups-missing-default-institute",
            "groups missing raw default institutes",
            "warning",
        ),
        (
            "groups-unmapped-default-institute",
            "groups with unmapped raw default institutes",
            "warning",
        ),
        (
            "template-unmapped-institutes",
            "templates using unmapped raw institutes",
            "warning",
        ),
        (
            "groups-with-multiple-template-institutes",
            "groups using multiple raw template institutes",
            "warning",
        ),
        (
            "unmapped-raw-institutes",
            "raw institutes missing canonical mappings",
            "warning",
        ),
        (
            "unknown-group-default-overrides",
            "group override entries not present in this environment",
            "warning",
        ),
        (
            "unused-canonical-institutes",
            "unused canonical institutes",
            "warning",
        ),
    )
    sections = _build_issue_sections(
        issue_buckets, section_specs, preview_limit=preview_limit
    )

    mapped_group_count = sum(
        1 for _group_id, expected in group_expected_canonical.items() if expected != ""
    )
    return {
        "summary": {
            "raw_institute_count": len(inst_status),
            "raw_institutes": sorted(inst_status.keys()),
            "active_group_count": len(active_group_rows),
            "groups_with_canonical_default_count": mapped_group_count,
            "template_entry_count": len(template_rows),
            "canonical_institute_count": len(canonical),
        },
        "sections": sections,
    }


def scan_admin_group_institute_schedule_history(
    mapping: Optional[Dict[str, Any]] = None,
    *,
    window_years: int = GROUP_INSTITUTE_HISTORY_WINDOW_YEARS,
    today: Optional[datetime.date] = None,
    preview_limit: Optional[int] = 10,
) -> GroupInstituteHistoryScanResult:
    normalized_mapping = (
        _parse_group_institute_mapping_payload(mapping)
        if isinstance(mapping, dict)
        else get_admin_group_institute_mapping()
    )
    context = _group_institute_scan_context(normalized_mapping)
    inst_status = context["inst_status"]
    known_groups = context["known_groups"]
    group_expected_canonical = context["group_expected_canonical"]
    resolved_window_years = normalize_group_institute_history_window_years(window_years)
    window_end = today or datetime.date.today()
    window_start = window_end - datetime.timedelta(days=365 * resolved_window_years)

    schedule_statement = (
        select(
            model.ScheduleEntry.date,
            model.ScheduleEntry.hour,
            model.ScheduleEntry.device,
            model.ScheduleEntry.orig_group,
            model.ScheduleEntry.orig_inst,
            model.TemplateEntry.template,
        )
        .outerjoin(
            model.TemplateEntry,
            model.ScheduleEntry.template == model.TemplateEntry.id,
        )
        .where(model.ScheduleEntry.date >= window_start)
        .where(model.ScheduleEntry.date <= window_end)
    )
    schedule_rows = model.db.session.execute(schedule_statement).all()

    aggregate_buckets: Dict[str, Dict[Tuple[str, ...], Dict[str, Any]]] = defaultdict(
        dict
    )

    def sample_label(
        row_date: datetime.date,
        hour: int,
        device_id: str,
        template_id: str,
    ) -> str:
        sample = f"{device_id} {row_date.isoformat()} {int(hour):02d}:00"
        if template_id != "":
            sample += f" template {template_id}"
        return sample

    def add_aggregate(
        section_id: str,
        issue_key: Tuple[str, ...],
        *,
        label: str,
        detail_prefix: str,
        sample: str,
    ) -> None:
        bucket = aggregate_buckets[section_id]
        item = bucket.get(issue_key)
        if item is None:
            item = {
                "label": label,
                "detail_prefix": detail_prefix,
                "count": 0,
                "examples": [],
            }
            bucket[issue_key] = item
        item["count"] += 1
        if (
            sample != ""
            and sample not in item["examples"]
            and len(item["examples"]) < 3
        ):
            item["examples"].append(sample)

    for row_date, hour, device_id, group_id, raw_inst, template_id in schedule_rows:
        group_key = _normalize_text(group_id)
        raw_institute = _normalize_text(raw_inst)
        device_key = _normalize_text(device_id)
        template_key = _normalize_text(template_id)
        sample = sample_label(row_date, int(hour), device_key, template_key)

        if group_key == "" or group_key not in known_groups:
            label = group_key or "(blank group)"
            add_aggregate(
                "recent-schedule-unknown-groups",
                (label,),
                label=label,
                detail_prefix=(
                    f"Recent schedule rows refer to group {label}, but that group is "
                    "not present in this environment."
                ),
                sample=sample,
            )
            continue

        if raw_institute == "":
            add_aggregate(
                "recent-schedule-missing-raw-institutes",
                (group_key,),
                label=group_key,
                detail_prefix=(
                    f"Recent schedule rows for group {group_key} are missing "
                    "orig_instcode values."
                ),
                sample=sample,
            )
            continue

        resolved_slot = _resolve_canonical_institute(raw_institute, normalized_mapping)
        if resolved_slot == "":
            inst_meta = inst_status.get(raw_institute)
            raw_label = raw_institute
            if inst_meta is not None:
                raw_label = f"{raw_institute} ({inst_meta['label']})"
            add_aggregate(
                "recent-schedule-unmapped-institutes",
                (group_key, raw_institute),
                label=f"{group_key}:{raw_institute}",
                detail_prefix=(
                    f"Recent schedule rows for group {group_key} use raw institute "
                    f"{raw_label}, but it does not resolve to any canonical institute."
                ),
                sample=sample,
            )
            continue

        expected = group_expected_canonical.get(group_key, "")
        if expected == "" or resolved_slot == expected:
            continue
        if any(
            _group_institute_exception_matches(
                exception,
                group=group_key,
                device=device_key,
                template=template_key,
                raw_institute=raw_institute,
                canonical_institute=resolved_slot,
            )
            for exception in normalized_mapping["exceptions"]
        ):
            continue

        add_aggregate(
            "recent-schedule-default-mismatches",
            (group_key, raw_institute, resolved_slot, expected),
            label=f"{group_key}: {resolved_slot} != {expected}",
            detail_prefix=(
                f"Recent schedule rows for group {group_key} resolve raw institute "
                f"{raw_institute} to {resolved_slot}, but the current group default "
                f"resolves to {expected}."
            ),
            sample=sample,
        )

    issue_buckets: Dict[str, List[GroupInstituteIssueRow]] = defaultdict(list)
    flagged_schedule_row_count = 0
    for section_id, bucket in aggregate_buckets.items():
        items = sorted(
            bucket.values(), key=lambda item: (-item["count"], item["label"])
        )
        for item in items:
            flagged_schedule_row_count += int(item["count"])
            detail = (
                f"{item['detail_prefix']} Rows in {resolved_window_years}-year window: "
                f"{item['count']}."
            )
            if item["examples"]:
                detail += " Examples: " + "; ".join(item["examples"]) + "."
            issue_buckets[section_id].append(
                {
                    "label": item["label"],
                    "detail": detail,
                    "count": int(item["count"]),
                }
            )

    section_specs = (
        (
            "recent-schedule-default-mismatches",
            "recent schedule rows that differ from current group defaults",
            "warning",
        ),
        (
            "recent-schedule-unmapped-institutes",
            "recent schedule rows using unmapped raw institutes",
            "warning",
        ),
        (
            "recent-schedule-missing-raw-institutes",
            "recent schedule rows missing raw institutes",
            "warning",
        ),
        (
            "recent-schedule-unknown-groups",
            "recent schedule rows referencing unknown groups",
            "warning",
        ),
    )

    sections = _build_issue_sections(
        issue_buckets, section_specs, preview_limit=preview_limit
    )
    return {
        "summary": {
            "window_years": resolved_window_years,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "schedule_entry_count": len(schedule_rows),
            "flagged_schedule_row_count": flagged_schedule_row_count,
            "issue_count": sum(section["issue_count"] for section in sections),
        },
        "sections": sections,
    }


def export_group_institute_issue_rows(
    mapping: Optional[Dict[str, Any]] = None,
    *,
    include_recent_history: bool = False,
    window_years: int = GROUP_INSTITUTE_HISTORY_WINDOW_YEARS,
    today: Optional[datetime.date] = None,
) -> Tuple[Tuple[str, ...], List[Tuple[str, ...]]]:
    headers = (
        "scope",
        "window_start",
        "window_end",
        "category",
        "severity",
        "count",
        "label",
        "detail",
    )
    rows: List[Tuple[str, ...]] = []

    current_scan = scan_admin_group_institute_mapping(mapping, preview_limit=None)
    for section in current_scan["sections"]:
        for item in section["rows"]:
            rows.append(
                (
                    "current-config",
                    "",
                    "",
                    section["id"],
                    section["severity"],
                    str(item.get("count", 1)),
                    str(item["label"]),
                    str(item["detail"]),
                )
            )

    if include_recent_history:
        history_scan = scan_admin_group_institute_schedule_history(
            mapping,
            window_years=window_years,
            today=today,
            preview_limit=None,
        )
        history_summary = history_scan["summary"]
        for section in history_scan["sections"]:
            for item in section["rows"]:
                rows.append(
                    (
                        "recent-schedule-history",
                        str(history_summary["window_start"]),
                        str(history_summary["window_end"]),
                        section["id"],
                        section["severity"],
                        str(item.get("count", 1)),
                        str(item["label"]),
                        str(item["detail"]),
                    )
                )

    return headers, rows


__all__ = [
    "GROUP_INSTITUTE_HISTORY_WINDOW_YEARS",
    "admin_group_institute_mapping_uses_recommended_default",
    "export_group_institute_issue_rows",
    "format_admin_group_institute_mapping_for_form",
    "get_admin_group_institute_mapping",
    "get_admin_group_institute_mapping_error",
    "parse_admin_group_institute_mapping",
    "recommended_group_institute_mapping",
    "scan_admin_group_institute_mapping",
    "scan_admin_group_institute_schedule_history",
    "set_admin_group_institute_mapping",
]
