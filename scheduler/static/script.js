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

function json_or(s, v) {
	try {
		return JSON.parse(s);
	} catch (SyntaxError) {
		return v;
	}
}

function wire_editor_expando() {
	const editor = document.querySelector(".schedule-editor");
	if (!editor) {
		return;
	}
	editor.addEventListener("click", evt => {
		// make sure we have an expando button
		const t = evt.target;
		if (t.tagName != "BUTTON" || !('expands' in t.dataset)) {
			return;
		}
		// parse expands, make sure it's a valid list of rows, and load the referenced nodes
		const controls = document.querySelectorAll(
			json_or(t.dataset['expands'], []).filter(i => /^row-\d+/.test).map(s => '#' + s).join(',')
		);
		// get the next state
		const expanded = !to_bool(t.getAttribute("aria-expanded"));
		// toggle the off hour rows
		for (const c of controls) {
			c.hidden = !expanded;
		}
		// update the button state
		t.setAttribute("aria-expanded", from_bool(expanded));
	});
	// show buttons and enable expando styles
	editor.querySelectorAll(".expando button").forEach(e => e.hidden = false);
	editor.classList.add("js-expando");
}

const base = json_or(document.querySelector("#app-root").innerText, "/");

function main() {
	enforce_datalists();
	clear_server_errors_on_input();
	setup_auto_confirms();
	wire_editor_expando();
}
main();