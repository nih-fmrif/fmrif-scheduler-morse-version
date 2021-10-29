---
title: 'Scheduler schema'
lof: true
...
\pagebreak
# Scheduler schema

The schema is separated into two halves:

* a legacy section that has been used for many years
* a new section that was added to make the scheduler self-contained

These will be documented separately.

There is almost no reason to use the database directly, except for generating analytics and that will generally only involve the legacy section. In general, it is not recommended to update the database directly as there are many invariants maintained by the site that cannot be expressed in the database. Exceptions to this rule will be noted. Except for a very few tables that will be noted it is not in general safe to delete rows from a table.

\pagebreak

![Simplified ER diagram](er-diagram.svg){ width=100% }

The Simplified ER diagram shows the relationships between relevant tables and columns. Deprecated tables, deprecated columns, and views are omitted. Legacy tables and legacy columns are shaded. Primary keys are bold. Foreign keys are italic. An edge in the graph between tables means there is at least one foreign key relationship between them. This is only meant as a brief overview.

\pagebreak
## Legacy section
