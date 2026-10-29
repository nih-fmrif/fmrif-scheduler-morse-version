# Mapping Organizational Groups Resolution Path

> Historical design or review notes. This records earlier work and may not
> describe the current application. Start with [the documentation index](../README.md).

## Purpose

This document defines what "fully resolved" means for organization mapping and
what the next operational steps are once the current issue backlog is low.

It is not a call for immediate hard enforcement. It is a migration target.

## Resolved State

Treat organization mapping as "resolved enough" when all of the following are
true in the active environment:

- every active group has a raw default institute in `tlkpdept.inst`
- every active group default resolves to one canonical institute
- every raw institute used by active groups or templates is either canonical or
  mapped by alias
- every active template slot either matches the group default canonically or has
  an explicit exception
- recent schedule-history issues are either eliminated or reduced to documented
  exceptions
- inactive or unknown institutes are not used by active groups/templates
- unused canonical entries have been reviewed and are either removed or kept
  intentionally

This does not require rewriting all historical schedule rows.

## Migration Path

### 1. Stabilize the overlay

- finish the canonical institute set
- finish alias mappings for known raw values
- review operational pseudo-institutes such as `DEV`, `MAINT`, `TRAIN`, and
  `NMRF`
- encode intentional mismatches as explicit exceptions

### 2. Clear current-configuration issues

- fill missing `tlkpdept.inst` values for active groups
- remove inactive institute references from active groups/templates
- reduce multi-institute template usage per group unless it is intentional
- resolve unknown group overrides

This is the highest-value cleanup because it affects current editing behavior.

### 3. Clear recent-history issues

- review unexplained `tblsched.orig_instcode` mismatches within the selected
  review window
- decide whether each mismatch is:
  - historical noise that can remain
  - a real current drift problem that should be fixed in group/template config
  - a durable exception that belongs in the overlay

Recent schedule history should be used as evidence, not as a direct rewrite
target.

### 4. Freeze the baseline

Once the overlay is stable:

- keep the canonical set under admin control
- treat new unmapped raw values as drift to review quickly
- treat new template/group mismatches as warnings by default

At this point the scanner becomes a drift monitor instead of a discovery tool.

### 5. Normalize current configuration selectively

Only after the overlay is trusted:

- normalize active `tlkpdept.inst` values where the raw value is just a legacy
  alias
- normalize active `tbltemplate.instcode` values where there is no documented
  exception
- leave `tblsched.orig_instcode` as historical evidence unless there is a
  separate audited cleanup project

This step should always be previewable and auditable.

## Next Steps After Resolution

Once organization mapping is stable, the next implementation layer should be:

1. non-blocking editor warnings in the template editor
2. guided admin fixes for defaults, aliases, and exceptions
3. optional enforcement for newly created data only

The recommended order matters. Editor warnings help validate the model before
guided fixes and enforcement are added.

## What Not To Do

- do not bulk rewrite historical schedule rows as part of "resolution"
- do not make the NIH public list the only allowed vocabulary
- do not block production-compatible raw values before exceptions and aliases are
  mature
- do not collapse operational pseudo-institutes into NIH institutes just to make
  the model look cleaner

## Implementation Note

If we move beyond documentation and small admin-surface changes into guided
fixes, normalization actions, or editor enforcement, that should be done in the
original organization-mapping worktree so the larger slice stays isolated.
