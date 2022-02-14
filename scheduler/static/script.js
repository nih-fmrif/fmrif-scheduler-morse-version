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

	for (const input of inputs) {
		input.addEventListener("input", evt => {
			// clear invalid flag whenever input is changed.
			input.setCustomValidity('');
			// run validation
			validate_and_normalize(evt.target);
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
		// toggle the off hour rows
		for (const c of controls) {
			c.hidden = !expanded;
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
			acc.push('the ${kind} request:<ul>');
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

function main() {
	enforce_datalists();
	clear_server_errors_on_input();
	setup_auto_confirms();
	wire_editor_expando();
	wire_log_buttons();
}
main();