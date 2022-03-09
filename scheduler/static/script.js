import A11yDialog from "./a11y-dialog/dialog.js";
import { enableBodyScroll, disableBodyScroll } from "./scroll-lock/body-scroll-lock.js";

function get_datalists() {
	const elms = document.querySelectorAll("datalist");
	const out = new Map();
	for (const elm of elms) {
		if (!elm.id) {
			console.warn("datalist without id");
			break;
		}
		const canonical = new Map();
		for (const opt of elm.options) {
			if (opt.disabled) {
				continue;
			}
			// labels are always plaintext
			const lbl = opt.innerText;
			const id = opt.value;
			// this is wrong if two ids have the same label
			// but we ensure that this never happens server side
			// by rendering labels as "label (id)" whenever label != id
			canonical.set(lbl, id);
			canonical.set(id, id);
		}
		const errorMessage = elm.dataset.errorMessage ?? 'invalid value';
		out.set(elm.id, { canonical, errorMessage });
	}
	return out;
}

function enforce_datalists() {
	const inputs = [...document.querySelectorAll("input[list]")];

	if (inputs.length == 0) {
		return;
	}
	const forms = new Set(inputs.map(elm => elm.form));

	const datalists = get_datalists();
	if (datalists.size == 0) {
		console.warn("there are inputs with the list attribute but no datalists");
		return;
	}

	const validate_and_normalize = input => {
		const dl = datalists.get(input.list.id)
		if (!dl) {
			// result of programming error, let it be handled server side
			// as there is nothing sensible that we can do here
			console.warn(`unknown list id ${input.list.id}`);
			return true;
		}
		if (!input.value) {
			// consider blank valid, let built in required attr handle this case
			return true;
		}
		const canon = dl.canonical.get(input.value);
		if (!canon) {
			input.setCustomValidity(dl.errorMessage);
			return false;
		}
		input.value = canon;
		return true;
	};

	for (const form of forms) {
		form.addEventListener("submit", evt => {
			for (const input of inputs) {
				if (input.form != form) {
					continue;
				}

				if (!validate_and_normalize(input)) {
					input.reportValidity();
					evt.preventDefault();
				}
			}
		});
	}

	// re-validate inputs if the list changes
	const mo = new MutationObserver(ms => {
		for (const m of ms) {
			const t = m.target;
			if (t.list != null) { // can be null when between lists
				t.setCustomValidity("");
				validate_and_normalize(t);
			}
		}
	});

	for (const input of inputs) {
		validate_and_normalize(input);
		input.addEventListener("input", evt => {
			const t = evt.target;
			// clear invalid flag whenever input is changed.
			t.setCustomValidity('');
			// run validation
			validate_and_normalize(t);
		});
		mo.observe(input, {
			attributes: true,
			attributeFilter: ['list'],
		});
	}
}

function clear_server_errors_on_input() {
	document.querySelectorAll("input[aria-describedby]").forEach(elm => {
		//describedby may contain id of an error list
		const ids = elm.getAttribute("aria-describedby").split(" ").filter(s => /-err$/.test(s));
		if (ids.length != 1) {
			return;
		}
		const list = document.getElementById(ids[0])
		if (!list) {
			console.warn(`${ids[0]} does not refer to error-list`);
			return;
		}
		// flag this as invalid client-side so invalid icon is shown
		elm.setCustomValidity("errors from server side validation");
		// if the input changes, set it valid and remove the error list
		elm.addEventListener("input", () => {
			elm.setCustomValidity("");
			list.remove();
		}, { "once": true });
	});
}

async function confirmDialog(titleText, message, opts = {}) {
	return new Promise((resolve, _) => {
		const con = document.getElementById('confirm-dialog-container');
		const modal = con.querySelector(".dialog-box-container");
		const title = con.querySelector("#dialog-title");
		const body = con.querySelector(".dialog-content-inner");
		const cancel = con.querySelector("button[name=cancel]");
		const confirm = con.querySelector("button[name=confirm]");
		title.innerText = titleText;
		body.innerHTML = message;
		if (opts.cancel) {
			cancel.innerText = opts.cancel;
		}
		if (opts.confirm) {
			confirm.innerText = opts.confirm;
		}
		const dialog = new A11yDialog(con);
		dialog.on("show", () => {
			// scroll lock and focus cancel button
			disableBodyScroll(modal);
			cancel.focus();
		});
		dialog.on("hide", (_, evt) => {
			enableBodyScroll(modal);
			// only true if confirm button was used
			resolve(Boolean(evt.target && evt.target.name && evt.target.name == "confirm"))
			// reset template
			title.innerText = "";
			body.innerHTML = "";
			cancel.innerText = "cancel";
			confirm.innerText = "confirm";
		});
		dialog.show();
	});
}

function setup_auto_confirms() {
	// old safari lacks the tools to do this safely
	// so it does not get this progressive enhancement
	const test = document.createElement('form');
	if (!('requestSubmit' in test)) {
		return;
	}

	document.querySelectorAll("form[method=post]").forEach(form => {
		form.addEventListener("submit", evt => {
			const src = evt.submitter;
			const ds = src.dataset;
			// only show dialog if the corresponding html api used
			if ('confirmTitle' in ds) {
				// if this is set we've already shown the dialog,
				// so proceed without interruption.
				if (form.dataset.Fired == "true") {
					delete form.dataset.Fired;
					return;
				}
				form.dataset.Fired = true;
				evt.preventDefault();

				const msg = ds.confirmMsg ?? "Are you sure?";
				const opts = {};
				if (ds.confirmCancel) {
					opts['cancel'] = ds.confirmCancel;
				}
				if (ds.confirmConfirm) {
					opts['confirm'] = ds.confirmConfirm;
				}

				confirmDialog(ds.confirmTitle, msg, opts).then(confirmed => {
					if (!confirmed) {
						delete form.dataset.Fired;
						return;
					}
					evt.target.requestSubmit(src);
				});
			}
		});
	});
}

function to_bool(s) {
	if (s == "true") {
		return true;
	} else if (s == "false") {
		return false;
	}
	return undefined;
}

function from_bool(b) {
	if (b) {
		return "true";
	}
	return "false";
}

function closestButtonWith(target, tag) {
	target = target.closest("button");
	if (target == null) {
		return null;
	}
	if (tag in target.dataset) {
		return target;
	}
	return null;
}

function json_or(s, v) {
	try {
		return JSON.parse(s);
	} catch (SyntaxError) {
		return v;
	}
}

function wire_editor_expando() {
	const expando = document.querySelector("#expando");
	if (!expando) {
		return;
	}
	expando.addEventListener("click", evt => {
		// parse expands, make sure it's a valid list of rows, and load the referenced nodes
		const controls = document.querySelectorAll(
			json_or(expando.dataset['expands'], []).filter(i => /^\d+$/.test).map(s => '#row-' + s).join(',')
		);
		// get the next state
		const expanded = !to_bool(expando.getAttribute("aria-expanded"));
		if (expanded) {
			// unhide any hidden rows
			for (const c of controls) {
				c.hidden = false;
			}
		} else {
			// hide rows unless they contain a changed cell
			for (const c of controls) {
				if (c.querySelector("entry-cell[data-changed=true]") == null) {
					c.hidden = true;
				}
			}
		}
		// update the button state
		expando.setAttribute("aria-expanded", from_bool(expanded));
	});
	expando.hidden = false;
}

const base = json_or(document.querySelector("#app-root").innerText, "/");

async function loadLog(id, signal) {
	try {
		const resp = await fetch(`${base}json/v1/log/${id}`, { signal });
		if (!resp.ok) {
			return [null, `error: api returned with error code ${resp.status}`];
		}
		const data = await resp.json();
		return [data, null];
	} catch (err) {
		if (err instanceof AbortError) {
			return [null, null];
		} else if (err instanceof SyntaxError) {
			return [null, "error: invalid json returned from api"];
		} else {
			return [null, `error: ${e.message}`];
		}
	}
}

const time_formatter = new Intl.DateTimeFormat('en-US', {
	year: 'numeric',
	month: 'short',
	day: 'numeric',
	hour: 'numeric',
	minute: 'numeric',
	second: 'numeric',
});

// used to sort values in fmt_log
const _fmt_log_order = {
	'group': 0,
	'researcher': 1,
	'used': 2,
	'filed_by': 3,
	'note': 4,
	'fulfilled_by': 5,
	'approved': 6,
};

function _fmt_log_entry(k, v) {
	if (v == null) {
		return '<i>nothing</i>';
	}
	switch (k) {
		case 'used':
			v = v ? 'used' : 'unused';
			break;
		case 'approved':
			v = v ? 'approved' : 'unapproved';
			break;
	}
	return `<b>${v}</b>`;
}

function fmt_log(entries) {
	if (entries.length == 0) {
		return "no changes have been logged";
	}
	const acc = ['<ul>'];
	for (const entry of entries) {
		const by = entry.by ? `<b>${entry.by}</b>` : "<i>unknown</i>";
		const ts = time_formatter.format(new Date(entry.modified));
		const values = Object.entries(entry.values);

		acc.push(`<li> on ${ts}, ${by} changed `);
		if (entry.kind == 'main') {
			acc.push('the entry:<ul>');
		} else {
			acc.push(`the ${kind} request:<ul>`);
		}

		// sort values by key according to _fmt_log_order.
		values.sort((a, b) => _fmt_log_order[a[0]] - _fmt_log_order[b[0]]);

		for (let [k, [Old, New]] of values) {
			const label = k.replace(/_/, ' ');
			const fOld = _fmt_log_entry(k, Old);
			const fNew = _fmt_log_entry(k, New);
			acc.push(`<li>set ${label} from ${fOld} to ${fNew}</li>`);
		}
		acc.push('</ul></li>')
	}
	acc.push('</ul>');
	return acc.join('');
}

function logDialog(titleText, id) {
	const con = document.getElementById('log-dialog-container');
	const modal = con.querySelector(".dialog-box-container");
	const title = con.querySelector("#log-dialog-title");
	const body = con.querySelector(".dialog-content-inner");
	title.innerText = titleText;
	const dialog = new A11yDialog(con);
	const abort = new AbortController();
	dialog.on("show", async () => {
		// scroll lock and focus cancel button
		disableBodyScroll(modal);

		const [data, err] = await loadLog(id, abort.signal);
		if (err != null) {
			body.innerText = err;
			return;
		}
		body.innerHTML = fmt_log(data);
	});
	dialog.on("hide", (_, evt) => {
		// reset scroll lock, zero template, and cancel http requests
		enableBodyScroll(modal);
		title.innerText = "";
		body.innerHTML = "";
		abort.abort();
	});
	dialog.show();
}

function wire_log_buttons() {
	const editor = document.querySelector(".schedule-editor");
	if (!editor) {
		return;
	}
	editor.addEventListener("click", evt => {
		const t = closestButtonWith(evt.target, 'for');
		if (t == null) {
			return;
		}
		const id = t.dataset["for"];
		if (!/\d+/.test(id)) {
			console.warn(["invalid data-for on log button", t]);
			return;
		}
		logDialog("history", id);
	});
	editor.querySelectorAll("entry-cell button[data-for]").forEach(e => e.hidden = false);
	editor.classList.add('js-log-buttons');
}

class Grid {
	constructor(container, table, cells) {
		this.container = container;
		this.table = table;
		this.cells = cells;
		this.setRow(this.firstVisibleRow());
		this.setCol(0);
		this.setOpen(false);
	}
	row() {
		return parseInt(this.table.dataset.row, 10);
	}
	col() {
		return parseInt(this.table.dataset.col, 10);
	}
	setRow(r) {
		this.table.dataset.row = r;
	}
	setCol(c) {
		this.table.dataset.col = c;
	}
	pos() {
		return [this.row(), this.col()];
	}
	isOpen() {
		return to_bool(this.table.dataset.open);
	}
	setOpen(v) {
		this.table.dataset.open = from_bool(v);
	}
	selectedCell() {
		return this.cells[this.row()][this.col()];
	}
	rowHidden(r) {
		// tr hidden when off hours and not toggled open.
		return this.cells[r][0].parentElement.hidden;
	}
	maxRow() {
		return this.cells.length - 1;
	}
	maxCol() {
		return this.cells[0].length - 1;
	}
	firstVisibleRow() {
		let n = 0;
		while (this.rowHidden(n)) {
			n++;
		}
		return n;
	}
	lastVisibleRow() {
		let n = this.maxRow();
		while (this.rowHidden(n)) {
			n--;
		}
		return n;
	}
	rowStart() {
		return this.focus(this.row(), 0);
	}
	rowEnd() {
		return this.focus(this.row(), this.maxCol());
	}
	colStart() {
		return this.focus(this.firstVisibleRow(), this.col());
	}
	colEnd() {
		return this.focus(this.lastVisibleRow(), this.col());
	}
	first() {
		return this.focus(this.firstVisibleRow(), 0);
	}
	last() {
		return this.focus(this.lastVisibleRow(), this.maxCol());
	}
	left() {
		let [row, col] = this.pos();
		col--;
		if (col < 0) {
			return false;
		}
		return this.focus(row, col);
	}
	right() {
		let [row, col] = this.pos();
		col++;
		if (col > this.maxCol()) {
			return false;
		}
		return this.focus(row, col);
	}
	up() {
		let [row, col] = this.pos();
		row--;
		if (row < 0) {
			return false;
		}
		while (this.rowHidden(row)) {
			row--;
			if (row < 0) {
				return false;
			}
		}
		return this.focus(row, col);
	}
	down() {
		let [row, col] = this.pos();
		const maxRow = this.maxRow();
		row++;
		if (row > maxRow) {
			return false;
		}
		while (this.rowHidden(row)) {
			row++;
			if (row > maxRow) {
				return false;
			}
		}
		return this.focus(row, col);
	}
	select(row, col) {
		// out of bounds, ignore
		if (row < 0 || col < 0 || row > this.maxRow() || col > this.maxCol()) {
			return false;
		}
		// if we're trying to select a hidden row,
		// arbitrarily select the first row that is not hidden.
		if (this.rowHidden(row)) {
			row = this.firstVisibleRow();
		}
		this.setRow(row);
		this.setCol(col);
		return true;
	}
	focus(row, col, force = false) {
		if (!this.select(row, col)) {
			return false;
		}

		// skip if the cell already contains the cursor
		// unless force is specified which we use to handle ESC key
		const cell = this.selectedCell();
		if (!force && cell.matches(":focus-within")) {
			return false;
		}

		this.setOpen(false);
		cell.focus({
			preventScroll: true,
		});
		this.scrollIntoView(row, col);
		return true;
	}
	scrollIntoView(row, col) {
		if (!this.select(row, col)) {
			return;
		}
		this.selectedCell().scrollIntoView({
			"block": "center",
			"inline": "center",
		});
		// the first row and/or col does not take the table headings into account
		// so we detect these cases and issue a correction
		const firstCol = col == 0;
		const firstRow = row == this.firstVisibleRow();
		if (firstCol || firstRow) {
			const opts = {};
			if (firstCol) {
				opts.left = 0;
			}
			if (firstRow) {
				opts.top = 0;
			}
			this.container.scroll(opts);
		}
	}
}

// focusables_around returns the focusable items immediately before and after elm.
// it is only designed to work on the editor pages.
function focusables_around(elm) {
	// note that this works because querySelectorAll returns elements in document order
	// and we know that there is always at least one focusable before and after elm
	let before = null;
	for (const f of document.querySelectorAll("a,button,input")) {
		switch (elm.compareDocumentPosition(f)) {
			case Node.DOCUMENT_POSITION_PRECEDING:
				// the last time we set this will be the focusable directly before elm
				before = f;
				break;
			case Node.DOCUMENT_POSITION_FOLLOWING:
				return [before, f];
		}
	}
}

// edge_focusables returns the first and last focusable elements of a gridcell.
// if there is only one it returns it twice. There cannot be zero.
function edge_focusables(elm) {
	const fs = elm.querySelectorAll(":is(input, button):not(:disabled)");
	return [fs[0], fs[fs.length - 1]];
}

function editor_grid() {
	const container = document.querySelector(".editor #scroll-container");
	if (container == null) {
		return;
	}
	const editor = container.querySelector(':scope>table');

	// create matrix indexing cells by (row, col)
	// and add extra attributes while we're in there
	const cells = [];
	editor.querySelectorAll('tbody tr').forEach(row => {
		const i = cells.push([]) - 1;
		row.querySelectorAll('td').forEach(col => {
			const j = cells[i].push(col) - 1;
			col.setAttribute("tabindex", "-1");
			col.setAttribute("role", "gridcell");
			col.dataset.row = i;
			col.dataset.col = j;
		});
	});

	const grid = new Grid(container, editor, cells);

	// we use these when handling tab from within the grid
	const [focusableBefore, focusableAfter] = focusables_around(container);

	// move focus to selected item in grid in the next microtask
	const focusContainer = evt => {
		container.scrollIntoView();
		setTimeout(() => {
			grid.focus(...grid.pos());
		}, 0);
	};

	container.addEventListener("focus", focusContainer);

	// set a trap so shift+tab from earlier in container doesn't end up in a grid cell.
	// (we always skip over it going the other direction)
	const focusTrap = document.querySelector("#focus-trap");
	focusTrap.setAttribute("tabindex", "0");
	focusTrap.addEventListener("focus", focusContainer);

	// if focus moves inside the grid,
	// make sure we update the selected cell in case it has changed
	const focusFixer = evt => {
		let t = evt.target;

		const setsInternalFocus = t.matches(":is(input, button, label):not(:disabled)");

		// if we're not a cell, see if we're in a cell
		if (!t.matches("td")) {
			t = t.closest("td");
		}
		if (t == null) {
			return;
		}

		const ds = t.dataset;
		grid.select(ds.row, ds.col);

		// mark grid open if we're focusing an input element
		if (setsInternalFocus && evt.type == "focusin") {
			grid.setOpen(true);
			grid.scrollIntoView(ds.row, ds.col);
		}
	};
	editor.addEventListener("focusin", focusFixer);
	editor.addEventListener("focusout", focusFixer);

	// if we click inside the grid without changing focus,
	// focus the correct cell
	editor.addEventListener("click", evt => {
		const t = evt.target;
		if (t.matches("td")) {
			grid.focus(t.dataset.row, t.dataset.col);
			evt.preventDefault();
		}
	});

	container.addEventListener("keydown", evt => {
		if (evt.isComposing || evt.keyCode == 229) {
			return;
		}

		// we only want to intercept esc and tab when we're in a cell
		if (grid.isOpen()) {
			switch (evt.key) {
				case "Esc":
				case "Escape":
					grid.focus(...grid.pos(), true)
					break;

				case "Tab":
					// if we're in a cell, only need to worry about focus exiting the cell
					const t = evt.target;
					const [first, last] = edge_focusables(grid.selectedCell());
					let leaving = false;
					if (evt.shiftKey) {
						// shift+tab on first element
						leaving = first == t;
					} else {
						// tab on last element
						leaving = last == t;
					}
					if (leaving) {
						grid.focus(...grid.pos(), true);
						evt.preventDefault();
					}
					break;
			}

			return;
		}

		// if we're not in cell, we need to intercept all grid keys
		switch (evt.key) {
			case "Left":
			case "ArrowLeft":
				grid.left();
				break;

			case "Right":
			case "ArrowRight":
				grid.right();
				break;

			case "Up":
			case "ArrowUp":
				grid.up();
				break;

			case "Down":
			case "ArrowDown":
				grid.down();
				break;

			case "Home":
				if (evt.ctrlKey) {
					grid.first();
				} else {
					grid.rowStart();
				}
				break;

			case "End":
				if (evt.ctrlKey) {
					grid.last();
				} else {
					grid.rowEnd();
				}
				break;

			case "PageDown":
				grid.colEnd();
				break;

			case "PageUp":
				grid.colStart();
				break;

			case "Enter":
				grid.setOpen(true);
				// focus first focusable in cell (always at least one)
				grid.selectedCell().querySelector(":is(input, button):not(:disabled)").focus();
				break;

			case "Tab":
				if (evt.shiftKey) {
					focusableBefore.focus();
				} else {
					focusableAfter.focus();
				}
				break;

			default:
				return
		}
		evt.preventDefault();
	});
	editor.setAttribute("role", "grid");
	container.classList.add("js-grid");
}

function editor_dialog(save, showNotifications, titleText, innerHTML, then) {
	const con = document.getElementById('save-dialog-container');
	const modal = con.querySelector(".dialog-box-container");
	const title = con.querySelector("#save-dialog-title");
	const body = con.querySelector(".dialog-content-inner");
	const cancel = con.querySelector("button[name=cancel]");
	const notificationsCon = con.querySelector(".dialog-form input-set");
	const notifications = notificationsCon.querySelector("#send-notifications");
	title.innerText = titleText;
	body.innerHTML = innerHTML;
	if (save) {
		cancel.hidden = false;
	}
	if (showNotifications) {
		notificationsCon.hidden = false;
	}
	const dialog = new A11yDialog(con);
	dialog.on("show", () => {
		// scroll lock and focus cancel button
		disableBodyScroll(modal);
		cancel.focus();
	});
	dialog.on("hide", (_, evt) => {
		enableBodyScroll(modal);
		// only follow continuation if confirm button was used
		if (evt.target && evt.target.name && evt.target.name == "confirm" && then) {
			then(notifications.checked);
		}
		// reset template
		title.innerText = "";
		body.innerHTML = "";
		cancel.hidden = true;
		notificationsCon.hidden = true;
	});
	dialog.show();
}

class SupportRequestSubForm {
	constructor(elm, parent, cfg) {
		this.elm = elm;
		this.isNew = to_bool(elm.dataset.new);
		this.kind = elm.dataset.sr;
		this.parent = parent;

		this.perms = cfg.perms;
		this.membership = cfg.membership;
		this.members = cfg.sr_members[this.kind];

		this.requested = elm.querySelector('.requested');
		this.handler = elm.querySelector('.handler');

		this.orig = {
			requested: to_bool(this.requested.dataset.orig),
			handler: this.handler.dataset.orig,
			subkind: "",
		};

		this.subkind_fieldset = elm.querySelector('fieldset'); // null if not tech
		this.subkind = null;
		if (this.kind == "tech") {
			// get the RadioNodeList of the radio group
			const radio = this.subkind_fieldset.querySelector('[type=radio]');
			this.subkind = radio.form.elements[radio.name];

			this.orig.subkind = this.subkind_fieldset.dataset.orig;
		}

		if (!this.editable) {
			return;
		}

		this.elm.disabled = false;
	}
	get changed() {
		if (this.requested.checked != this.orig.requested) {
			return true;
		}
		// only check subkind if it exists and there is a request
		if (this.requested.checked && this.subkind != null && this.orig.subkind != this.subkind.value) {
			return true;
		}
		return this.handler.value != this.orig.handler;
	}
	get invalid() {
		// the handler is the only element that can be in an invalid state
		// but we only report it if it's something the user can fix
		return this.handler_editable && !this.handler.validity.valid;
	}
	get editable() {
		// editable if part of an editable cell and there exists someone to fulfill the request
		return this.members.size > 0 && this.parent.editable;
	}
	get handler_editable() {
		// each kind has the same name as the corresponding perm.
		return this.editable && this.perms[this.kind];
	}
	diff() {
		if (!this.changed) {
			return null;
		}
		const changes = {};
		if (this.requested.checked != this.orig.requested) {
			// only one other option so no need to store both values
			changes.requested = this.requested.checked;
		}
		if (this.handler.value != this.orig.handler) {
			changes.handler = [this.orig.handler, this.handler.value];
		}
		if (this.subkind != null) {
			if (this.isNew) {
				// simplify backend code by including this implicit transition in the diff
				changes.subkind = ["", this.subkind.value];
			} else if (this.subkind.value != this.orig.subkind) {
				changes.subkind = [this.orig.subkind, this.subkind.value];
			}
			// always grab this for printing summary.
			changes.effectiveSubkind = this.subkind.value;
		}
		return changes;
	}
	reset() {
		this.requested.checked = this.orig.requested;
		this.handler.value = this.orig.handler;
		if (this.subkind != null) {
			this.subkind.value = this.orig.subkind;
		}
	}
}

class Cell {
	constructor(elm, cfg) {
		this.elm = elm;
		this.perms = cfg.perms;
		this.membership = cfg.membership;
		this.device_groups = cfg.device_groups;
		this.schedulable_groups = cfg.schedulable_groups;
		this.colors = cfg.colors;

		// institute may be null depending on the page
		this.institute = elm.querySelector('input[id^=ins-]');
		this.group = elm.querySelector('input[id^=grp-]');
		this.member = elm.querySelector('input[id^=mem-]');
		this.legend = elm.querySelector('entry-legend');

		this.id = elm.dataset.id;

		// note that date is very different depending on the editor used
		this.hour = elm.dataset.hour;
		this.date = elm.dataset.date;

		// data-old is undefined in template editor so we simplify that to false.
		this.old = to_bool(elm.dataset.old) ?? false;

		this.orig = {
			institute: this.institute?.dataset.orig,
			group: this.group.dataset.orig,
			member: this.member.dataset.orig,
		};

		// gather any support requests
		const subforms = [...elm.querySelectorAll("fieldset[data-sr]")];
		const kv = subforms.map(sr => [
			sr.dataset.sr,
			new SupportRequestSubForm(sr, this, cfg),
		]);
		this.sr = Object.fromEntries(kv);

		// nothing further to do unless this is an editable cell
		if (!this.editable) {
			return;
		}

		if (this.institute) {
			this.institute.disabled = false;
		}
		this.group.disabled = false;
		this.member.disabled = false;
		this.update_list();

		this.elm.addEventListener("input", evt => {
			this.update_list();
			this.update_swatch();
			this.fire_change();
		});
	}
	get changed() {
		if (this.institute && this.orig.institute != this.institute.value) {
			return true;
		}
		for (const sr of Object.values(this.sr)) {
			if (sr.changed) {
				return true;
			}
		}
		return (this.orig.group != this.group.value) || (this.orig.member != this.member.value);
	}
	get invalid() {
		if (!this.editable) {
			// cell state may be incorrect but the user can do nothing about it.
			return false;
		}
		if (this.institute && !this.institute.validity.valid) {
			return true;
		}
		for (const sr of Object.values(this.sr)) {
			if (sr.invalid) {
				return true;
			}
		}
		return !this.group.validity.valid || !this.member.validity.valid;
	}
	get editable() {
		if (this.perms.edit_any) {
			return true;
		}
		if (this.perms.edit && !this.old) {
			const g = this.orig.group;
			if (!this.device_groups.has(g)) {
				// if the original group no longer belongs to the device, consider the slot up for grabs
				return true;
			}
			// Otherwise, consider a cell editable if it was editable
			// when the editor was loaded even if the user had set
			// the cell to a group they don't belong to, allowing them to undo a mistake
			return this.membership.has(this.orig.group);
		}
		return false;
	}
	diff() {
		if (!this.changed) {
			return null;
		}
		// start off with the metadata
		const changes = {
			"id": this.id,
			"date": this.date,
			"hour": this.hour,
		};
		if (this.institute && this.orig.institute != this.institute.value) {
			changes.institute = [this.orig.institute, this.institute.value];
		}
		if (this.orig.group != this.group.value) {
			changes.group = [this.orig.group, this.group.value];
		}
		if (this.orig.member != this.member.value) {
			changes.member = [this.orig.member, this.member.value];
		}
		for (const [kind, sr] of Object.entries(this.sr)) {
			const sr_changes = sr.diff();
			if (sr_changes) {
				changes[kind] = sr_changes;
			}
		}
		return changes;
	}
	reset() {
		if (this.institute) {
			this.institute.value = this.orig.institute;
		}
		this.group.value = this.orig.group;
		this.member.value = this.orig.member;
		for (const sr of Object.values(this.sr)) {
			sr.reset();
		}
		this.update_list();
		this.fire_change();
	}
	update_list() {
		const gv = this.group.value;
		let list = 'none'; // special list always empty to simplify checks
		// group has members, update list to point to appropriate datalist.
		if (this.schedulable_groups.has(gv)) {
			list = `members-of-${gv}`;
		}
		// only update the list if it's different than the current value
		// to avoid unnecessary revalidation
		if (this.member.list.id != list) {
			this.member.setAttribute("list", list);
		}
	}
	update_swatch() {
		this.legend.style.setProperty("--swatch", this.colors[this.group.value] ?? "transparent");
	}
	fire_change() {
		this.elm.dispatchEvent(new CustomEvent('cell_change', {
			bubbles: true,
			detail: this,
		}));
	}
}

function json_from_script_or(id, def) {
	const script = document.querySelector('script[type="application/json"]#' + id);
	if (!script) {
		return def;
	}
	const text = script.textContent;
	if (!text) {
		return def;
	}
	// we do not use json_or here as text MUST be valid json;
	return JSON.parse(text);
}

function datalist_ids_or(id, def) {
	const dl = document.querySelector('datalist#' + id);
	if (!dl) {
		return def;
	}
	return [...dl.options].map(opt => opt.value);
}

function fmt_sr_diff(acc, k, sr) {
	// count the number of changes in the diff
	// if the count is one, we can present a simpler summary
	// also note whether the subkind changed.
	let n = 0;
	let changesSubkind = false;
	const has = f => Number(f != undefined); // 0 if undefined, 1 otherwise
	n += has(sr.requested);
	n += has(sr.handler);
	// only count subkind if it transitioned from a previous value
	// otherwise it would always be reported the first time
	if (sr.subkind && sr.subkind[0] != "") {
		n++;
		changesSubkind = true;
	}

	// compute the human name of this SR
	let name = {
		"tech": "technologist",
		"train": "training",
		"med": "medical",
	}[k];
	// for tech requests, include the subkind in the name
	// unless the subkind has changed (per the definition above)
	// since that gets reported on its own
	if (k == "tech" && !changesSubkind) {
		name = `${name} (${sr.effectiveSubkind})`;
	}
	name += ' request';

	// format the individual diffs, if they exist
	let requested = "";
	if (sr.requested != undefined) {
		if (sr.requested) {
			requested = "<i>filed</i>";
		} else {
			requested = "<i>canceled</i>";
		}
	}

	let handler = "";
	if (sr.handler != undefined) {
		const [Old, New] = sr.handler;
		if (New) {
			handler = `fulfilled by <b>${New}</b>`;
			if (Old) {
				handler += `(was <b>${Old}</b>)`;
			}
		} else {
			handler = `no longer fulfilled by <b>${Old}</b>`;
		}
	}

	let subkind = "";
	if (changesSubkind) {
		// only one other option so no need to report old value
		subkind = `changed to <i>${sr.subkind[1]}</i>`;
	}

	// n is at least 1 by construction
	if (n == 1) {
		acc.push(`<dd>${name} `);
		// only 1 of these isn't the empty string
		acc.push(requested, handler, subkind);
		acc.push('</dd>');
		return;
	}

	// we have at least 2 changes, use a sub-dl
	acc.push(`<dd><dl><dt>${name}:</dt>`);
	const push = s => {
		if (s) {
			acc.push('<dd>', s, '</dd>');
		}
	};
	push(requested);
	push(subkind);
	push(handler);
	acc.push('</dl></dd>');
}

function fmt_editor_diffs(templateEditor, diffs) {
	const acc = ['<dl>'];
	let notifications = 0;
	const recordTransition = (k, a, b) => {
		// return if this is notification worthy
		if (a == "") {
			acc.push(`set ${k} to <b>${b}</b>`);
			return 1;
		} else if (b == "") {
			acc.push(`cleared ${k} (was <b>${a}</b>)`);
			return 0;
		} else {
			acc.push(`set ${k} to <b>${b}</b> (was <b>${a}</b>)`);
			return 1;
		}
	};
	const add = (diff, k) => {
		const rec = diff[k];
		if (!rec) {
			return;
		}
		const [a, b] = rec;
		acc.push('<dd>');
		const ret = recordTransition(k, a, b);
		acc.push('</dd>');
		return ret;
	};
	for (const diff of diffs) {
		acc.push(`<dt>${diff.date}: ${diff.hour}</dt>`); // TODO need to humanize these values
		notifications += add(diff, 'institute');
		notifications += add(diff, 'group');
		notifications += add(diff, 'member');
		for (const k of ['tech', 'train', 'med']) {
			const sr = diff[k];
			if (sr) {
				fmt_sr_diff(acc, k, sr);
			}
		}
	}
	acc.push('</dl>');
	return [!templateEditor && (notifications > 0), acc.join('')];
}

function wire_cell_editors() {
	const container = document.querySelector(".editor #scroll-container tbody");
	if (container == null) {
		return;
	}
	const templateEditor = document.querySelector('form.editor').classList.contains('template-editor');

	// if this is missing, we're on a template page so everything is true
	const perms = json_from_script_or("user-perms", {
		"edit": true,
		"edit_any": true,
		"medical": true,
		"tech": true,
		"training": true
	});

	// if this is missing we're on a template page so edit_any is true and it's irrelevant
	const membership = new Set(json_from_script_or("user-groups", []));
	membership.add(""); // consider every one a member of the null group

	const device_groups = new Set(json_from_script_or("device-groups", []));
	const colors = json_from_script_or("group-colors", {});

	const tech_members = new Set(datalist_ids_or("tech", []));
	const train_members = new Set(datalist_ids_or("train", []));
	const med_members = new Set(datalist_ids_or("med", []));

	// get a set of all group names for groups that have member lists
	const schedulable_groups = new Set([...document.querySelectorAll('datalist[id^=members-of-]')].map(
		elm => elm.id.slice("members-of-".length)
	));

	const cfg = {
		perms,
		membership,
		device_groups,
		schedulable_groups,
		colors,
		"sr_members": {
			"tech": tech_members,
			"train": train_members,
			"med": med_members,
		},
	};


	const cells = [...container.querySelectorAll("td entry-cell")].map(elm => new Cell(elm, cfg));

	// keep track of changed and invalid cells
	const changed = new Set();
	const any_changed = () => Boolean(changed.size);
	const invalid = new Set();
	const any_invalid = () => Boolean(invalid.size);
	const changedInvalid = new Set();
	// no cells can be changed yet but they could have come invalid
	for (const cell of cells) {
		if (cell.invalid) {
			invalid.add(cell);
		}
	}

	// keep caption in sync with cell updates
	const caption = document.querySelector("#caption");
	const update_caption = (which, bool) => {
		caption.dataset[which] = from_bool(bool);
	};
	update_caption("error", any_invalid());
	container.addEventListener("cell_change", evt => {
		const cell = evt.detail;
		console.log("diff", cell.diff()); // XXX for debugging

		if (cell.invalid) {
			invalid.add(cell);
		} else {
			invalid.delete(cell);
		}
		update_caption("error", any_invalid());

		if (cell.changed) {
			changed.add(cell);
		} else {
			changed.delete(cell);
		}
		update_caption("changed", any_changed());

		if (cell.changed && cell.invalid) {
			changedInvalid.add(cell);
		} else {
			changedInvalid.delete(cell);
		}
	});

	const apply = document.querySelector("#apply");
	apply.disabled = false;
	apply.addEventListener("click", evt => {
		evt.preventDefault();
		if (!any_changed()) {
			editor_dialog(false, false, "no changes", "there are no changes to submit", null);
		} else if (changedInvalid.size > 0) {
			editor_dialog(false, false, "outstanding errors", "all errors must be resolved in updated entries before submitting", null);
		} else {
			// at least one cell is changed and no changed cells contain errors
			const diffs = [];
			for (const cell of changed) {
				diffs.push(cell.diff());
			}
			// order the diffs by civil time
			diffs.sort((a, b) => {
				if (a.date < b.date) {
					return -1;
				} else if (a.date > b.date) {
					return 1;
				}
				if (a.hour < b.hour) {
					return -1;
				} else if (a.hour > b.hour) {
					return 1;
				}
				return 0;
			});
			let [notifications, summary] = fmt_editor_diffs(templateEditor, diffs);
			editor_dialog(true, notifications, "publish changes", summary, checked => {
			});
		}
	});
}

function main() {
	enforce_datalists();
	clear_server_errors_on_input();
	setup_auto_confirms();
	wire_editor_expando();
	editor_grid();
	wire_log_buttons();
	wire_cell_editors();
}
main();