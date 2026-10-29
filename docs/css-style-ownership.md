# CSS Style Ownership

`scheduler/static/base.css` is now import-order only. Surface ownership lives in
the following files:

- `scheduler/static/css/tokens.css`: global tokens, normalization, root element
  defaults, and foundational typography/color variables.
- `scheduler/static/css/layout.css`: global layout, shell/navigation, shared
  cards/panels, and non-feature-specific page structure.
- `scheduler/static/css/forms.css`: device/group membership and form-composition
  patterns shared across scheduler and admin pages.
- `scheduler/static/css/editor.css`: scheduler editor and RBAC explorer
  interaction/layout styling.
- `scheduler/static/css/admin.css`: app issues, audit tables/filters, and admin
  surface refinements.

Rule of thumb for feature edits:

- Scheduler editor and matrix interactions: `editor.css`
- RBAC and app-issues admin controls/tables: `admin.css`
- Shared form structure/fieldset behavior: `forms.css`
- Header/nav/page shell and shared cards: `layout.css`
- New variables/theme primitives: `tokens.css`
