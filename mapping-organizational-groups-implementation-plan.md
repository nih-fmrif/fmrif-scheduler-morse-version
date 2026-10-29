# Mapping Organizational Groups Implementation Plan

## Goal

Implement a production-compatible institute and group harmonization layer that improves admin clarity, surfaces issues quickly, and avoids rewriting or over-constraining live data.

## Phase 1: Clarify Existing Semantics

Deliverables:

- add inline admin help explaining that legacy CSV `dept` headers currently carry group ids
- capture the policy in `mapping-organizational-groups-policy.md`
- keep current behavior unchanged

Checks:

- route test for the admin issues page
- `pixi run pre-commit`

## Phase 2: Add Admin Mapping Storage

Deliverables:

- add a new admin JSON setting for canonical institute mapping
- parse and validate it in `scheduler/logic/admin_config.py`
- render it in the admin panel using the same edit pattern as mailing lists

Preferred storage:

- `app_settings` row
- candidate key: `core.group_institute_mapping`

Validation rules:

- canonical institute ids must be unique
- raw aliases must map to exactly one canonical institute
- group default overrides must reference existing groups
- exceptions must be structurally valid but should not require templates/groups to exist at parse time if we want safe staged edits

## Phase 3: Add Read-Only Admin Issue Scanner

Deliverables:

- compute harmonization issues from:
  - `tlkpinst`
  - `tlkpdept.inst`
  - `tbltemplate.instcode`
  - the canonical mapping JSON
- expose results in the admin panel as a dedicated issue section

Issue categories:

- missing-group-institute
- inactive-group-institute
- unmapped-raw-institute
- ambiguous-raw-alias
- group-with-multiple-raw-institutes
- template-group-institute-mismatch
- unused-canonical-institute

Severity guidance:

- warning: no canonical mapping, unused canonical values
- medium: group missing institute, inactive institute still referenced
- high: ambiguous mapping, mismatched template/group institute without exception

## Phase 4: Add Editor Warnings

Deliverables:

- show non-blocking warnings in the template editor when a slot institute differs from the group default
- link warnings back to the admin issue definitions
- do not reject saves yet

## Phase 5: Guided Fixes

Deliverables:

- provide explicit admin actions for safe fixes:
  - set group default institute
  - add raw alias mapping
  - add exception
  - mark canonical institute inactive
- audit each change

Do not include in this phase:

- silent bulk rewrites
- automatic template rewrites without preview
- hard validation that blocks historical data entry

## Phase 6: Optional Hardening

Only after issue counts are low and the exception model is proven:

- consider rejecting obviously invalid institute ids in new admin-managed mappings
- consider stronger save-time warnings or limited enforcement for newly created data only

## Testing Plan

- unit tests for admin mapping JSON parsing and validation
- route tests for admin panel rendering and save flows
- unit tests for harmonization issue generation
- route contract updates if new endpoints are added
- `pixi run pre-commit`

## Suggested First Implementation Slice

1. Add `core.group_institute_mapping` admin JSON storage.
2. Add read-only issue generation.
3. Add a compact admin issues panel with counts and example rows.

That slice gives immediate operational value without changing scheduler behavior.
