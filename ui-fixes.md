Top navigation bar
- The navigation buttons should be responsive and shrink to icons on a narrow display. Use a minimalist black and white icon of an human MRI scanner for the homepage button. The space between all icons should shrink to an equal width before button size is reduced.

Homepage

- A search filter that has the same behavior as the rbac search filters should exist for both groups and devices i.e. debounced, filters even if only one letter has been search, only searches the names
 - If required for a user (as in they have more than 5 items), a "show more" button should provide an option to expand the items displayed beyond the default of 5.

Device schedule page
- Remove the dynamic text that says something like  “schedule for Test Scanner from 2026-01-05 to 2026-01-11”. It is not required. All that text can be removed from the interface.
- Merge the jump navigation and slot status card into a single sticky control card above the grid header.
- In that merged card remove the horizontal divider, the schedule text/icon block, and the control for choosing the number of displayed days. The current responsive column behavior is sufficient.
- From the slot status card keep only the three buttons: `View`/`View/Edit`, `Review pending`, and `Legend`.
- Selecting previous/next non empty should not reload the page or jump the location on the page. These controls should be compact rewind/fast-forward arrow buttons with hover-tip explanations, provide clicked feedback, and alter the displayed dates in place.
- Replace “selected slot details” in the slot modal with “Selection Details”.
- The default text content of the slot status should be “Select a time slot”, and nothing else. Upon selection it should display the selected slot, summary, number of changes, and number of errors
- The slot status card should also contain a "View" button and a "Legend" button with the former displaying "View/Edit" if edit permissions exist
- The default date in the jump to element should be the current date.
- By default without space constraints and previous navigation history the schedule should be 7 days wide and should start on Monday.
- The max col width should be defined such that there is no horizontal scrollbar on the schedule regardless of the display width. This may only be a single column on narrow displays... this means current date would show by default rather than the Monday.
- The timeslot labels should be fixed width.
- A horizontal scroll moves to adjacent columns and hides columns on the opposite side of the schedule in a smooth manner. Similarly the arrow buttons should move a single day to the left or right. This lateral movement should occur without reloading the page or changing the url. It should also occur regardless  of any cell in the current or adjacent cols.
- Ideally vertical scrolling is not captured by the schedule grid and simply scrolls the page as normal i.e the grid has no scrollbars and the grid captures horizontal scrolling but not vertical scrolling.
- The “view/edit” button should just display view when the user has read-only access. Previously selecting a cell provided edit access… the form that used to be present should be integrated with the current view/edit modal when edit permissions are available. The save button should be moved into this modal. The legend button should be moved to where the save button is currently.
- Selecting different slots should have no effect on the location of the schedule view (currently it causes a ui jump) and should instead highlight that cell and show the corresponding slot status
- Remove the dynamic row hydration text such as “all 24 rows ready”.
- The current column header should include the year only once, at the start of the visible header on the left, as range metadata.
- Currently the navigation bar always stays visible upon vertical scroll. This should instead happen for the merged scheduler control card and the schedule header i.e. the date/day for each column. The Date should be in parenthesis after the day and be formatted <month as a three letter abbreviation - date as two digits>.

RBAC page
- Keep the full RBAC audit log on `/rbac` (admin-only section), and remove it from the Admin Panel page.

Admin panel page
- The content needs to fit on narrow displays without scrolling horizontally.
- Potential issues sections: these should be collapsed by default, even after running a detection scan.
