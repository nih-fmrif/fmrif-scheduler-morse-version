-- there are many color columns on tlkpdept where only one is used. Simplify

begin;

-- add a default color to colorless
update tlkpdept set color_wkday_day = '000000' where coalesce(color_wkday_day, '') = '';

-- normalize on 6 digit colors, expand ABC to AABBCC
update tlkpdept
	set color_wkday_day =
		substr(color_wkday_day, 1, 1) || substr(color_wkday_day, 1, 1) ||
		substr(color_wkday_day, 2, 1) || substr(color_wkday_day, 2, 1) ||
		substr(color_wkday_day, 3, 1) || substr(color_wkday_day, 3, 1)
	where length(color_wkday_day) = 3;

alter table tlkpdept add column color varchar(7);
comment on column tlkpdept.color is 'legend color on site';

-- save color in same format as input type=color uses
update tlkpdept set color = '#' || lower(color_wkday_day);

-- make sure all future colors fit this exact pattern
alter table tlkpdept alter column color set not null;
alter table tlkpdept add constraint tlkpdept_valid_color check (color ~ '^#[0-9a-f]{6}$');

-- dump old columns as they're only used by the site
alter table tlkpdept drop column color_wkday_day;
alter table tlkpdept drop column color_wkday_eve;
alter table tlkpdept drop column color_wkend_day;
alter table tlkpdept drop column color_wkend_eve;


commit;
