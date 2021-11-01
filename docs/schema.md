---
title: 'Scheduler schema'
lof: true
...
\pagebreak
# Scheduler schema

The schema is separated into two halves:

* a legacy section that has been used for many years
* a modern section that was added to make the scheduler self-contained

These will be documented separately.

There is almost no reason to use the database directly, except for generating analytics and that will generally only involve the legacy section. In general, it is not recommended to update the database directly as there are many invariants maintained by the site that cannot be expressed in the database. Exceptions to this rule will be noted. Except for a very few tables that will be noted it is not in general safe to delete rows from a table.

\pagebreak

![Simplified ER diagram](er-diagram.svg){ width=100% }

The Simplified ER diagram shows the relationships between relevant tables and columns. Deprecated tables, deprecated columns, and views are omitted. Legacy tables and legacy columns are shaded. Primary keys are bold. Foreign keys are italic. An edge in the graph between tables means there is at least one foreign key relationship between them. This is only meant as a brief overview.

\pagebreak
## Legacy section

In exploring the db, you may see tables or columns with the comment "Deprecated". These contain historical data for older entries and can be ignored. They will not be detailed here.

### tlkpinst

This table stores institutes and is one of the few tables that can be modified directly. The **instcode** column is the primary key which is referenced by other tables. The **inst** column is the display name for the institute. A retired institute can be marked inactive by setting the **active** column to `false`.

To add a new institute, use
```sqlpostgresql
insert into tlkpinst(instcode, inst) values ('CODE', 'display label');
```

To update the label, use
```sqlpostgresql
update tlkpinst set inst = 'new display label' where instcode = 'CODE';
```

To deactivate an institute use
```sqlpostgresql
update tlkpinst set active = false where instcode = 'CODE';
```

### tlkpresearcher

This table stores users. The **researchercode** stores the AD username that comes via SiteMinder. It is referenced many times from other tables. Some entries predate **researchercode** coming from SiteMinder and can be ignored. The **name** column stores the display name from SiteMinder and **email** stores the email from SiteMinder. The **active** column is false for users who no longer have access to the site. The **chg_at** column is a timestamp of the last modification to the user.

### tlkpscanner

This table stores devices. The **scannercode** is the primary key referenced by many tables. The **scanner** column contains the human readable label, which must be unique, and **descrip** contains a human readable description. The **active** column is `true` for devices that are listed on the site.

The remaining columns are email addresses (multiple addresses being separated by commas)

* **mailinglist** are the addresses for notifying of schedule changes
* **techaddr** are the addresses for notifying of technologist requests
* **medaddr** are the addresses for notifying of medical coverage requests
* **trainaddr** are the addresses for notifying of training requests

### tlkpdept

This table lists groups. The **deptcode** column is the primary key referenced by many tables. The **dept_short** column is the human readable label, which must be unique. The **dept** column is the human readable description, which also must be unique. The **iscurrent** column is `true` for active groups. 

The **inst** column is a foreign key to the [*tlkpinst*](#tlkpinst) that this group belongs to, if any.

The **color** column contains the color used in the schedule in the same format used by the html `type=color` input element.

The **link** column contains links that describe the group, if any.

Many groups are special and should never be modified. Nonspecial groups are marked by the generated **department** column evaluating to `true`. The **ismain**, **joinable**, **archivable**, and **schedulable** columns are used to generate this information. They must never be changed but can safely be ignored.

### tbltemplates

This table lists templates per device. The primary key is a composite of a **templatecode** and a foreign key reference **scannercode**. The **template** column is a human readable label and **comments** a human readable description. The **hidden** column is `true` if this template is archived.

### tbltemplate

This table lists the entries for a given template referenced by the (**templatecode**, **scannercode**) columns. The **templateid** is the primary key. The (**dow**, **hour**) columns represent the (day of week, hour) coordinates to set in the schedule (see [*tblsched*](#tblsched) for more information) and the optional foreign keys **deptcode**, **researchercode**, and **instcode** represent the values to set in the schedule when its template is applied to the schedule.

### tblsched

This is the main table of interest as it contains the schedule.

The **schedid** column is the primary key of the table.

The **templateid** column is a reference to the [*tbltemplate* entry](#tbltemplate) that created this column. It may be `null` for historical entries but it will never be `null` for any modern entries as modern entries are always created from a template.

The **chg_at** column represents a last modification date for the entry and may be `null` for historical entries. The **chg_by** column records who made the last modification and may be `null` for historical entries. The **chg_by** column is a string and for historical entries does not refer to a user of the website.

The **scannercode** column is a reference to the device that this entry applies to. The **scheddate** is the civil date this entry applies to and the **schedhour** column is the 24 hour civil time of the entry. These three columns are coordinates that uniquely identify a schedule entry.

The **scheddow** column represents the day of week of the entry (0 = Sunday) and it forms a separate week-local coordinate system along with **schedhour**. This is important in [*tbltemplate*](#tbltemplate) but can be ignored in this table. For modern entries, for each device and week, every value of **schedhour** and **scheddow** will be present in this table even if they are never modified after the template is applied.

The **time_used** column reports whether the device was used as scheduled. It is a nullable bool where `null` should be understood as "not yet known". It is updated periodically from a separate database and is not meant to be modified directly.

The **orig_deptcode** and **orig_instcode** columns refer to the group and institute as recorded in the template that was used to create this entry.

The **deptcode** and **researchercode** columns are the group and user that are currently scheduled for this entry.

Support requests are encoded by the [support and supportkind](#support-and-supportkind) tables.

Changes to this table are recorded in the [*tlogsched*](#tlogsched) audit table.

### tlogsched

Entries in this table are automatically created by the **log_sched_changes** trigger whenever and however the schedule is modified.

The **logid** column is the primary key of the table.

The **schedid** column refers to an entry in *tblsched*. This will be `null` if the entry was deleted. Modern entries will never be deleted. The **scannercode**, **scheddate**, and **schedhour** correspond to the columns in *tblsched*. These are redundant for modern entries and are only of use if **schedid** is `null`.

The **chg_at** and **chg_by** columns are identical to those in *tblsched* but correspond to the change that caused this row to be created.

The remaining rows come in pairs of `X` and `X_old` for `X` in **deptcode**, **researchercode**, **time_used**. For these `X` refers to the value after the schedule entry was changed and `X_old` refers to the value before the entry was changed. 

There are also **scannercode_old**, **scheddate_old**, and **schedhour_old** and while these are dutifully logged, none of these would ever change unless someone was modifying the schedule directly in the database and not going through the site, which is inadvisable.

## Modern

### support and supportkind

The *supportkind* table is an enum that should never be changed except by an application developer. It consists of a primary key **supportkind** and a label **label**.

The *support* table represents support requests for schedule entries. It's primary key is a composite of the foreign keys (**schedid**, **supportkind**). This means that there can be up to 3 support entries for each entry in the schedule.

The **chg_at** column records the last modification date. The **chg_by** column references the *tlkpresearcher* entry for the user that last modified the support request.

The **filed_by** column references the user that filed this support request and **fulfilled_by** references the user that answered the request.

The **approved** column is a nullable boolean that records whether the support request was approved where `null` should be understood as "not yet decided".

The **note** column is currently only to record the difference in technologist requests but is left vague to allow future changes as well.

Changes to *support* are recorded in [*supportlog*](#supportlog).

### supportlog

Entries in this table are automatically recorded by the **log_support_changes** trigger whenever and however *support* is modified.

The **logid** column is the primary key.

The (**schedid**, **supportkind**) pair duplicate the primary key of the *support* entry in question.

The **chg_by** and **chg_at** columns are the values of the same columns in *support* at the time this row was created.

The remaining columns follow the `X`, `X_old` pattern of [*tlogsched*](#tlogsched).

### app_log_json

This is a view that combines all the *tlogsched* and *supportlog* entries for a single **schedid** into a json document in the **entries** column that filters out much of the noise. It is meant to be used as
```sqlpostgresql
select entries from app_log_json where schedid = :id
```
and it is not a good idea to run it for many more than a single entry as it is quite expensive relative to other queries in this schema.

The json document consists of a list of objects. Each object has **modified** (**chg_at**), **chg_by**, **kind**, and **values** keys. The **kind** is 'main' for *tlogsched* entries and *supportkind.label* otherwise and **values** is an object of `X_old`, `X` value pairs keyed by `X` and consisting of the list `[X_old, X]` that are only include when `X_old≠X`.

This should never need to be used directly as the website will report this in a nicely formatted manner.

### devicegroup

This table consists of (**scannercode**, **deptcode**) pairs meaning that group **deptcode** has access to device **scannercode** when both are active. If one or both are inactive, then it is ignored. It is safe to insert and delete rows from the table, but using the website is preferable.

### groupmembers and primarygroupmember

The *groupmembers* table records the state of user membership in a group. The primary key is the composite foreign key (**deptcode**, **researchercode**).

The **approve1** and **approve2** columns are `null` or a timestamp for when the appropriate approval was recorded. If one or both are `null` the user is not in the group yet but has requested to be in the group. Most groups only require one approval so the columns are either both `null` or the same timestamp. The row will be deleted if approval is denied.

The **approved** generated column is `true` iff both **approve1** and **approve2** are not `null`.

The *primarygroupmember* consists only of the pair **deptcode** and **researchercode** where the corresponding pair must exist in *groupmembers*. An entry in this table means that the respective user is the primary investigator of the respective group.

It is safe to delete an approved row from *groupmembers* iff there does not exist a corresponding row in *primarygroupmember*. It is always safe to delete an unapproved row.

### membership

The *membership* view simplifies membership queries. It is used by the website so it may not be changed but it can be used.

The **"group"** column is the **deptcode** and the **"user"** column is the **researchercode** (note the quoting is necessary as these are reserved words in postgres. The remaining columns are all boolean:

* **approved** if the user is approved to be in the group
* **pi** if the user is the primary investigator of the group
* **group_active** if the group is active
* **user_active** if the user is active

To see all active members of groups, you can query
```sqlpostgresql
select "group", "user" from membership
where approved
and group_active
and user_active;
```

To see all users pending membership in group `X`, you can query
```sqlpostgresql
select "user" from membership where "group" = 'X' and not approved;
```

### userdevice

This table records the special per-device permissions for members of the DEV special group.

The primary key is (**researchercode**, **scannercode**) and the entry is meaningless if the user is not an active member of the DEV group.

The remaining columns are booleans corresponding to each of the special permissions with the additional constraint that at least one must be `true`.