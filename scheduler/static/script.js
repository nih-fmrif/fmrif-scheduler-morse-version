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
			input.reportValidity();
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
					evt.preventDefault();
				}
			}
		});
	}

	// on blur or form submit check [list] inputs against canonicalization (and valueMissing if required or is that handled?)
	for (const input of inputs) {
		input.addEventListener("blur", evt => {
			validate_and_normalize(evt.target);
		});
		input.addEventListener("input", evt => {
			// clear invalid flag whenever input is changed.
			input.setCustomValidity('');
			input.reportValidity();
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
		// if the input changes, remove the error list
		elm.addEventListener("input", () => list.remove(), { "once": true });
	});
}

function main() {
	enforce_datalists();
	clear_server_errors_on_input();
}
main();