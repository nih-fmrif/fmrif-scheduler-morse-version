# Mapping Organizational Groups Policy

## Purpose

This document defines the safest way to harmonize institute and group mapping in the scheduler without forcing production data into a prematurely tidy model.

The immediate goal is clarity and issue detection, not destructive normalization.

## Current Vocabulary

- `group`: the current logical RBAC and scheduling entity stored in `tlkpdept` and exposed as `Group.id`.
- `institute`: a raw value stored in `tlkpinst`, referenced by `tlkpdept.inst` for a group's default institute and by `tbltemplate.instcode` for a slot-level institute.
- `department`: legacy schema and CSV terminology. In current admin CSVs, the `dept` column contains current group ids.
- `canonical institute`: an overlay value used for reporting, issue detection, and eventual normalization guidance. It should not replace raw production-compatible values on first rollout.

## External Canonical Reference

Verified on March 12, 2026 against the official NIH Institutes and Centers page:
<https://www.nih.gov/about-nih/what-we-do/institutes-centers>

The current public NIH Institutes and Centers list is:

| Code | Name |
| --- | --- |
| `CC` | NIH Clinical Center |
| `CIT` | Center for Information Technology |
| `CSR` | Center for Scientific Review |
| `FIC` | Fogarty International Center |
| `NCATS` | National Center for Advancing Translational Sciences |
| `NCCIH` | National Center for Complementary and Integrative Health |
| `NCI` | National Cancer Institute |
| `NEI` | National Eye Institute |
| `NHGRI` | National Human Genome Research Institute |
| `NHLBI` | National Heart, Lung, and Blood Institute |
| `NIA` | National Institute on Aging |
| `NIAAA` | National Institute on Alcohol Abuse and Alcoholism |
| `NIAID` | National Institute of Allergy and Infectious Diseases |
| `NIAMS` | National Institute of Arthritis and Musculoskeletal and Skin Diseases |
| `NIBIB` | National Institute of Biomedical Imaging and Bioengineering |
| `NICHD` | Eunice Kennedy Shriver National Institute of Child Health and Human Development |
| `NIDA` | National Institute on Drug Abuse |
| `NIDCD` | National Institute on Deafness and Other Communication Disorders |
| `NIDCR` | National Institute of Dental and Craniofacial Research |
| `NIDDK` | National Institute of Diabetes and Digestive and Kidney Diseases |
| `NIEHS` | National Institute of Environmental Health Sciences |
| `NIGMS` | National Institute of General Medical Sciences |
| `NIMH` | National Institute of Mental Health |
| `NIMHD` | National Institute on Minority Health and Health Disparities |
| `NINDS` | National Institute of Neurological Disorders and Stroke |
| `NINR` | National Institute of Nursing Research |
| `NLM` | National Library of Medicine |

Inference from the official source: this 27-item NIH IC list is the right external baseline for canonical NIH institute values, but it is not sufficient by itself because scheduler data also contains operational pseudo-institutes.

## Current Runtime-Compatible Values

Observed in the current local runtime database on March 12, 2026:

- `DEV`
- `MAINT`
- `NCCIH`
- `NCI`
- `NEI`
- `NHGRI`
- `NHLBI`
- `NIAAA`
- `NIMH`
- `NINDS`
- `NMRF`
- `TRAIN`

This is intentionally not treated as the canonical list. It is a current runtime-compatible set. It already shows why a hard-coded NIH-only model would be too narrow:

- `DEV`, `MAINT`, and `TRAIN` are operational values, not NIH institutes.
- `NMRF` appears to be scheduler-local and should not be silently coerced into an NIH IC.
- the runtime set is only a subset of the official NIH IC list.

## Policy

1. Preserve raw production-compatible values.
   `tlkpinst`, `tlkpdept.inst`, and `tbltemplate.instcode` remain the raw system of record.

2. Introduce a canonical overlay, not a replacement.
   The canonical layer should exist to interpret and report on raw values, not to invalidate them on first rollout.

3. Distinguish institute classes.
   At minimum, support:
   - `nih_ic`
   - `local_operational`
   - `legacy_alias`
   - `unknown`

4. Treat `Group.inst` as the group default.
   This is the expected institute for the group, but not an immediate hard invariant for every historical template slot.

5. Treat template and schedule institute values as slot-level observations.
   They may differ from the group default for valid historical or operational reasons and must be reviewed before any enforcement is added.

6. Start with warning and issue generation.
   The first rollout should surface conflicts and suggested fixes in the admin panel, without blocking edits or rewriting historical data.

7. Do not silently normalize.
   Any proposed fix should be explicit, previewable, and auditable.

## Canonical Overlay Shape

The first implementation should use an admin-managed JSON document rather than a schema migration or hard-coded enum.

Suggested shape:

```json
{
  "canonical_institutes": {
    "NIMH": { "label": "National Institute of Mental Health", "kind": "nih_ic", "active": true },
    "NMRF": { "label": "NMRF", "kind": "local_operational", "active": true }
  },
  "raw_aliases": {
    "NIMH": "NIMH",
    "National Institute of Mental Health": "NIMH",
    "TRAIN": "TRAIN"
  },
  "group_defaults": {
    "LABX": "NIMH"
  },
  "exceptions": [
    {
      "group": "LABX",
      "template": "A",
      "reason": "historical shared-slot arrangement"
    }
  ]
}
```

## Admin Issues To Surface

- group has no default institute
- group default institute is inactive
- group default institute is not mapped to a canonical institute
- raw institute value exists but has no canonical mapping
- multiple raw institute values are used for the same group
- template slot institute differs from the group default and no exception exists
- canonical institute is defined but never used
- raw institute aliases map ambiguously

## Rollout Rules

- Phase 1 should be read-only except for editing the mapping JSON.
- Phase 2 can add editor warnings and issue links.
- Hard enforcement should not be considered until the issue backlog is low and intentional exceptions are encoded.

## Local Code References

- `scheduler/model.py`
- `scheduler/logic/admin_config.py`
- `scheduler/logic/schedule_editor.py`
- `scheduler/logic/templates.py`
- `scheduler/routes/_rbac_explorer_core.py`
