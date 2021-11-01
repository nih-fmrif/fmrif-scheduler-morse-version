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

In exploring the db, you may see tables or columns with the comment "Deprecated". These contain historical data for older entries and can be ignored. They will not be detailed here.

### tlkpinst

This table stores institutes and is one of the few tables that can be modified directly. The **instcode** column is the primary key which is referenced by other tables. The **inst** column is the display name for the institute. A retired institute can be marked inactive by setting the **active** column to false.

To add a new institute, use
```sql
insert into tlkpinst(instcode, inst) values ('CODE', 'display label');
```

To update the label, use
```sql
update tlkpinst set inst = 'new display label' where instcode = 'CODE';
```

To deactivate an institute use
```sql
update tlkpinst set active = false where instcode = 'CODE';
```

### tlkpresearcher

This table stores users. The **researchercode** stores the AD username that comes via SiteMinder. It is referenced many times from other tables. Some entries predate **researchercode** coming from SiteMinder and can be ignored. The **name** column stores the display name from SiteMinder and **email** stores the email from SiteMinder. The **active** column is false for users who no longer have access to the site. The **chg_at** column is a timestamp of the last modification to the user.

### tlkpscanner

This table stores devices. The **scannercode** is the primary key referenced by many tables. The **scanner** column contains the human readable label, which must be unique, and **descrip** contains a human readable description. The **active** column is false for devices that are listed on the site.

The remaining columns are email addresses (multiple addresses being separated by columns)

* **mailinglist** are the addresses for notifying of schedule changes
* **techaddr** are the addresses for notifying of technologist requests
* **medaddr** are the addresses for notifying of medical coverage requests
* **trainaddr** are the addresses for notifying of training requests

### tlkpdept

This table lists groups. The **deptcode** column is the primary key referenced by many tables. The **dept_short** column is the human readable label, which must be unique. The **dept** column is the human readable description, which also must be unique. The **iscurrent** column is true for active groups. 

The **inst** column is a foreign key to the [*tlkpinst*](#tlkpinst) that this group belongs to, if any.

The **color** column contains the color used in the schedule in the same format used by the html `type=color` input element.

The **link** column contains links that describe the group, if any.

Many groups are special and should never be modified. Nonspecial groups are marked by the generated **department** column evaluating to true. The **ismain**, **joinable**, **archivable**, and **schedulable** columns are used to generate this information and must never be changed and can safely be ignored.

### tbltemplates

This table lists templates per device. The primary key is a composite of a **templatecode** and a foreign key reference **scannercode**. The **template** column is a human readable label and **comments** a human readable description. The **hidden** column is true if this template is archived.

### tbltemplate

This table lists the entries for a given template referenced by the (**templatecode**, **scannercode**) columns. The **templateid** is the primary key. The (**dow**, **hour**) columns represent the (day of week, hour) coordinates to set in the schedule (see [*tblsched*](#tblsched) for more information) and the optional foreign keys **deptcode**, **researchercode**, and **instcode** represent the values to set in the schedule when its template is applied to the schedule.

### tblsched

This is the main table of interest as it contains the schedule.
