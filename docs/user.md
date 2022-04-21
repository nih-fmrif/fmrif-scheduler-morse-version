---
title: Scanner Scheduler User Manual
lof: true
...
\pagebreak
# Common elements

There are a number of common design elements used on the site that will be briefly discussed. These will likely be familiar from other websites and this section is meant as a quick orientation to the particulars of this site.

![Common page elements, annotated](common-elements.png){ width=100% }

1. The **breadcrumb** shows your position in the hierarchical structure of the site
2. The **user information** shows the username of the currently logged in user
3. The **tabs** show links to other pages in the current section
4. The **content area** shows the content of the current page

Both the breadcrumb and the tabs denote the current page with bold typeface. If there is only one page available to you in the current section, the tabs will not be shown.

\pagebreak
![Common form structure](common-form-1.png){ width=100% }

The red asterisk next to the label marks a field as required.

The smaller text below the input field provides additional description or help.

The blue ring around the second input shows which form element is currently active.

After the input field there is a validation status icon:

* a circled red exclamation point means the input is currently invalid and the form cannot be submitted
* a green checkmark indicates that the input is currently valid

![Server side errors](common-form-2.png){ width=100% }

Not all errors can be checked before the form is submitted to the server. If the server detects the error, the form will be returned with additional errors noted in the description. The errors are marked by a red exclamation point in a triangle.

\pagebreak
![Autocomplete Inputs](common-form-3.png){ width=100% }

Many fields autocomplete. Depending on the browser, clicking or double clicking a field will open the autocomplete. Otherwise begin typing and relevant options will be displayed and winnowed as you continue. The options in these fields will be of the form "human label (computer id)" and while both can be used in the autocomplete only the computer id portion is valid. For example, in the autocomplete pictured above you could start to type "pol" and "Bipolar Spectrum Disorder (BSD)" would be shown in the autocomplete. Selecting it will fill the field with "BSD". You could also have typed "BSD" directly and ignored the autocomplete's drop down.

\pagebreak
# The home page

The home page is a list of the main sections of the site.

1. [devices](#devices)
2. [groups](#groups)
3. [join form](#join-form)
4. [list action form](#list-action-form)

The [*groups*](#groups) section will only be shown if your account has access to it.

These sections will be explored from bottom to top. Many have subsections that only apply to users with higher administrative rights. If you do not see the links to an area being discussed, you can skip that portion of the documentation.

\pagebreak
# list action form
![list action form](list-action-form.png){ width=100% }

The list action form allows you to subscribe or unsubscribe from mailing lists relevant to this domain.

Your name and email will be populated from your login, but can be edited. Check the boxes in the lists to subscribe to/unsubscribe from (at least one must be selected). Then select the desired action.

\pagebreak
# join form

This form has a single autocomplete for all groups that you are not a member of currently. To request joining a group, use the autocomplete to select it and submit the form. Upon submission of this form, the primary investigator (**PI**) of the department will be emailed to confirm your membership.

The admin group has special protections and can only have members added by someone with direct access to the server. See cli.pdf for more information.

If you are a member of the DEV group but not a technologist, there will be a second page listed in the tabs. This page lets you attest to your qualification to be a technologist. However, the DEV PI must also assign you to devices as a technologist for you to be able to handle technology requests on those devices.

\pagebreak
# groups

Once you have been approved for at least one group, you can see the groups page. It will list all groups that you are a member of. Admins will see all groups as well as an option to see a list of groups that are no longer active and an option to add new groups.

A regular user will only be able to see basic information about the group and a list of fellow members. PI and admin will see additional tabs to alter membership, change the PI, and edit the group. These will be discussed in the following subsections. Regular users should skip ahead to the section on [*devices*](#devices).

\pagebreak
## membership

![membership alteration page](membership-list.png){ width=100% }

This page allows PI to remove members from their group. The PI is not listed on this page as the PI cannot be removed from the group. If there are pending members, they can be approved or denied from here (or from links in the notification email sent when the user submits the join form).

## change PI

This page has an autocomplete for approved members who are not currently the PI. If submitted, the designated member is the new PI and the old PI is a regular member, who can then be removed by the new PI if necessary.

## edit

![group edit (PI)](group-edit-pi.png){ width=100% }

![group edit (admin)](group-edit-admin.png){ width=100% }

The edit form has extra fields for admins.

The labels are used to describe the group to humans. The computer will always used the *deptcode* which is not editable.

The email or emails are used for any group notifications. The link is for other group members.

The legend color is the color this group will use in the scheduler. The color selection box is provided by the browser.

Admins can additionally change the institute associated with a group and uncheck the active box to make the group inactive.

## add group

![group add form](group-add.png){ width=100% }

The add group form is much like the group edit form but with two additional fields:

The deptcode field sets the id that this device will use for internal references.

The PI field selects an active user to be made the initial PI of the group. This is not an autocomplete as there are too many candidates. The username selected to be the PI must have been logged into the site at least once to be considered valid. An admin can always choose to make themselves PI and then use the change PI form later once the actual PI has joined the group.

\pagebreak
# devices

TODO