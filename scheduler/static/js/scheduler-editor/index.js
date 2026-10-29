import A11yDialog from "../../a11y-dialog/dialog.js";
import {
  enableBodyScroll,
  disableBodyScroll,
} from "../../scroll-lock/body-scroll-lock.js";
import {
  fmt_editor_diffs,
  fmt_log,
  fmt_save_results,
  humanize_date_if_needed,
  parse_schedule_cell_markup,
} from "./formatters.js";

const serverErrorState = new Map();

function announce(txt) {
  document.querySelector("#announce").innerText = txt;
}

function cssToken(value) {
  const token = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return token || "none";
}

const setBeforeUnload = (() => {
  // the beforeunload handler is added and removed as needed
  // as otherwise the browser will ignore a host of optimizations
  const beforeunload = [
    "beforeunload",
    (evt) => {
      evt.preventDefault();
      // unclear if setting the return value and returning a string
      // is still necessary for compatibility but doesn't harm anything
      evt.returnValue =
        "You have unsaved changes that will be lost. Are you sure?";
      return evt.returnValue;
    },
    { capture: true },
  ];
  return (on) => {
    if (on) {
      window.addEventListener(...beforeunload);
    } else {
      window.removeEventListener(...beforeunload);
    }
  };
})();

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
    const errorMessage = elm.dataset.errorMessage ?? "invalid value";
    out.set(elm.id, { canonical, errorMessage });
  }
  return out;
}

const datalist_validation_bound_inputs = new WeakSet();
const datalist_validation_bound_forms = new WeakSet();
let datalist_validation_observer = null;

function validate_and_normalize_datalist_input(input) {
  if (!(input instanceof HTMLInputElement) || !input.hasAttribute("list")) {
    return true;
  }

  const datalists = get_datalists();
  if (datalists.size == 0) {
    console.warn("there are inputs with the list attribute but no datalists");
    return true;
  }

  const listId = input.getAttribute("list") || "";
  const dl = datalists.get(listId);
  if (!dl) {
    // result of programming error, let it be handled server side
    // as there is nothing sensible that we can do here
    console.warn(`unknown list id ${listId}`);
    return true;
  }
  if (!input.value) {
    // consider blank valid, let built in required attr handle this case
    input.setCustomValidity("");
    return true;
  }
  const canon = dl.canonical.get(input.value);
  if (!canon) {
    input.setCustomValidity(dl.errorMessage);
    return false;
  }
  input.value = canon;
  input.setCustomValidity("");
  return true;
}

function bind_datalist_validation(input) {
  if (
    !(input instanceof HTMLInputElement) ||
    !input.hasAttribute("list") ||
    datalist_validation_bound_inputs.has(input)
  ) {
    return;
  }

  datalist_validation_bound_inputs.add(input);
  validate_and_normalize_datalist_input(input);

  input.addEventListener("input", (evt) => {
    const t = evt.target;
    if (!(t instanceof HTMLInputElement)) {
      return;
    }
    // clear invalid flag whenever input is changed.
    t.setCustomValidity("");
    // run validation
    validate_and_normalize_datalist_input(t);
  });

  const form = input.form;
  if (form && !datalist_validation_bound_forms.has(form)) {
    datalist_validation_bound_forms.add(form);
    form.addEventListener("submit", (evt) => {
      for (const field of form.querySelectorAll("input[list]")) {
        if (
          field instanceof HTMLInputElement &&
          !validate_and_normalize_datalist_input(field)
        ) {
          field.reportValidity();
          evt.preventDefault();
        }
      }
    });
  }

  if (datalist_validation_observer == null) {
    datalist_validation_observer = new MutationObserver((ms) => {
      for (const m of ms) {
        const t = m.target;
        if (!(t instanceof HTMLInputElement) || t.list == null) {
          continue;
        }
        // can be null when between lists
        t.setCustomValidity("");
        validate_and_normalize_datalist_input(t);
        t.dispatchEvent(new CustomEvent("list-change"));
      }
    });
  }

  datalist_validation_observer.observe(input, {
    attributes: true,
    attributeFilter: ["list"],
  });
}

function bind_datalist_validations(root = document) {
  if (root instanceof HTMLInputElement) {
    bind_datalist_validation(root);
    return;
  }
  if (!(root instanceof Document || root instanceof Element)) {
    return;
  }
  root.querySelectorAll("input[list]").forEach((input) => {
    bind_datalist_validation(input);
  });
}

function enforce_datalists() {
  bind_datalist_validations(document);
}

function clear_server_errors_on_input() {
  document.querySelectorAll("input[aria-describedby]").forEach((elm) => {
    //describedby may contain id of an error list
    const ids = elm
      .getAttribute("aria-describedby")
      .split(" ")
      .filter((s) => /-err$/.test(s));
    if (ids.length != 1) {
      return;
    }
    const list = document.getElementById(ids[0]);
    if (!list) {
      console.warn(`${ids[0]} does not refer to error-list`);
      return;
    }
    // flag this as invalid client-side so invalid icon is shown
    elm.setCustomValidity("errors from server side validation");
    // if the input changes, set it valid and remove the error list
    elm.addEventListener(
      "input",
      () => {
        elm.setCustomValidity("");
        list.remove();
      },
      { once: true },
    );
  });
}

async function parse_server_failure(resp) {
  const status = `${resp.status}${
    resp.statusText ? ` ${resp.statusText}` : ""
  }`;

  let json = null;
  try {
    json = await resp.clone().json();
  } catch (_err) {
    json = null;
  }

  if (json && typeof json == "object") {
    if (
      json.errors &&
      typeof json.errors == "object" &&
      !Array.isArray(json.errors)
    ) {
      return { data: json };
    }
    const errorList = Array.isArray(json.errors)
      ? json.errors
          .map((entry) => {
            if (typeof entry == "string") {
              return entry;
            }
            if (entry && typeof entry == "object") {
              if (typeof entry.message == "string") {
                return entry.message;
              }
              if (typeof entry.error == "string") {
                return entry.error;
              }
              return JSON.stringify(entry);
            }
            return "";
          })
          .filter((entry) => entry != "")
      : [];
    const message =
      typeof json.message == "string"
        ? json.message
        : typeof json.error == "string"
        ? json.error
        : errorList.join("; ");
    if (message) {
      return { message: `error: ${status}: ${message}` };
    }
  }

  let text = "";
  try {
    text = String(await resp.text()).trim();
  } catch (_err) {
    text = "";
  }
  const firstLine =
    text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line != "") ?? "";
  const detail = firstLine ? `: ${firstLine.slice(0, 220)}` : "";
  return { message: `error: ${status}${detail}` };
}

async function confirmDialog(titleText, message, opts = {}) {
  return new Promise((resolve) => {
    const con = document.getElementById("confirm-dialog-container");
    const modal = con.querySelector(".dialog-box-container");
    const title = con.querySelector("#dialog-title");
    const body = con.querySelector(".dialog-content-inner");
    const cancel = con.querySelector("button[name=cancel]");
    const confirm = con.querySelector("button[name=confirm]");
    title.innerText = titleText;
    body.textContent = String(message ?? "");
    if (opts.cancel) {
      cancel.innerText = opts.cancel;
    }
    if (opts.confirm) {
      confirm.innerText = opts.confirm;
    }
    let confirmed = false;
    const onConfirm = () => {
      confirmed = true;
    };
    const onCancel = () => {
      confirmed = false;
    };
    confirm.addEventListener("click", onConfirm);
    cancel.addEventListener("click", onCancel);
    const dialog = new A11yDialog(con);
    dialog.on("show", () => {
      // scroll lock and focus cancel button
      disableBodyScroll(modal);
      cancel.focus();
    });
    dialog.on("hide", () => {
      enableBodyScroll(modal);
      confirm.removeEventListener("click", onConfirm);
      cancel.removeEventListener("click", onCancel);
      resolve(confirmed);
      // reset template
      title.innerText = "";
      body.textContent = "";
      cancel.innerText = "cancel";
      confirm.innerText = "confirm";
    });
    dialog.show();
  });
}

function setup_auto_confirms() {
  // old safari lacks the tools to do this safely
  // so it does not get this progressive enhancement
  const test = document.createElement("form");
  if (!("requestSubmit" in test)) {
    return;
  }

  document.querySelectorAll("form[method=post]").forEach((form) => {
    form.addEventListener("submit", (evt) => {
      const src = evt.submitter;
      const ds = src.dataset;
      // only show dialog if the corresponding html api used
      if ("confirmTitle" in ds) {
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
          opts["cancel"] = ds.confirmCancel;
        }
        if (ds.confirmConfirm) {
          opts["confirm"] = ds.confirmConfirm;
        }

        confirmDialog(ds.confirmTitle, msg, opts).then((confirmed) => {
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

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function parse_ymd(ymd) {
  const parts = String(ymd ?? "")
    .trim()
    .split("-");
  if (parts.length != 3) {
    return null;
  }
  const [year, month, day] = parts.map((part) => Number.parseInt(part, 10));
  if (
    Number.isNaN(year) ||
    Number.isNaN(month) ||
    Number.isNaN(day) ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > 31
  ) {
    return null;
  }
  return new Date(Date.UTC(year, month - 1, day));
}

function ymd(date) {
  return date.toISOString().slice(0, 10);
}

function add_days(date, delta) {
  return new Date(date.getTime() + delta * MS_PER_DAY);
}

function days_since(start, end) {
  return Math.round((end.getTime() - start.getTime()) / MS_PER_DAY);
}

function replaceNodeContent(container, content) {
  if (content == null) {
    container.replaceChildren();
    return;
  }
  if (content instanceof Node) {
    container.replaceChildren(content);
    return;
  }
  container.textContent = String(content);
}

const JUMP_TO_NEXT_NON_EMPTY_DAY_EVENT =
  "fmrif:schedule-editor-next-non-empty-day";
const SHIFT_WINDOW_BY_EDGE_ARROW_EVENT =
  "fmrif:schedule-editor-shift-window-by-edge-arrow";
const JUMP_TO_WINDOW_EVENT = "fmrif:schedule-editor-jump-to-window";

function emit_jump_fallback(direction, row, col, source = "grid") {
  document.dispatchEvent(
    new CustomEvent(JUMP_TO_NEXT_NON_EMPTY_DAY_EVENT, {
      detail: { direction, row, col, source },
      bubbles: true,
    }),
  );
}

function emit_window_edge_shift(direction, row, col, source = "grid") {
  document.dispatchEvent(
    new CustomEvent(SHIFT_WINDOW_BY_EDGE_ARROW_EVENT, {
      detail: { direction, row, col, source },
      bubbles: true,
    }),
  );
}

function wire_editor_expando() {
  const expando = document.querySelector("#expando");
  if (!expando) {
    return;
  }
  expando.addEventListener("click", () => {
    // parse expands, make sure it's a valid list of rows, and load the referenced nodes
    const controls = document.querySelectorAll(
      json_or(expando.dataset["expands"], [])
        .filter((s) => /^\d+$/.test(s))
        .map((s) => "#row-" + s)
        .join(","),
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
    const label = expando.querySelector(".label");
    if (label) {
      label.innerText = expanded
        ? expando.dataset.lessLabel || "show less"
        : expando.dataset.moreLabel || "show more";
    }
    // update the button state
    expando.setAttribute("aria-expanded", from_bool(expanded));
  });
  expando.hidden = false;
}

function wire_jump_form() {
  const jumpForm = document.querySelector("nav.jump-form form");
  if (!jumpForm) {
    return;
  }

  const startInput = jumpForm.querySelector('input[name="start"]');
  const daysInput = jumpForm.querySelector('input[name="days"]');
  const pickerButton = jumpForm.querySelector("#jump-open-picker");
  if (!startInput || !daysInput) {
    return;
  }

  const buildJumpUrl = () => {
    const params = new URLSearchParams(window.location.search);
    params.set("start", startInput.value);
    params.set("days", daysInput.value);
    return `${window.location.pathname}?${params}`;
  };

  const applyJump = () => {
    if (!jumpForm.reportValidity()) {
      return;
    }
    const url = buildJumpUrl();
    const handledInPlace = !document.dispatchEvent(
      new CustomEvent(JUMP_TO_WINDOW_EVENT, {
        detail: {
          start: startInput.value,
          days: daysInput.value,
          url,
        },
        bubbles: true,
        cancelable: true,
      }),
    );
    if (!handledInPlace) {
      window.location.assign(url);
    }
  };

  let debounceTimer = null;
  const scheduleJump = () => {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = window.setTimeout(() => {
      applyJump();
    }, 500);
  };

  const onInput = () => {
    scheduleJump();
  };
  startInput.addEventListener("input", onInput);
  startInput.addEventListener("change", onInput);
  daysInput.addEventListener("input", onInput);
  if (pickerButton instanceof HTMLButtonElement) {
    pickerButton.addEventListener("click", (evt) => {
      evt.preventDefault();
      startInput.focus({ preventScroll: true });
      if (typeof startInput.showPicker == "function") {
        try {
          startInput.showPicker();
          return;
        } catch (_err) {
          // Some browsers restrict showPicker to trusted contexts. Focusing
          // the native date input is the fallback.
        }
      }
      startInput.click();
    });
  }
  jumpForm.addEventListener("submit", (evt) => {
    evt.preventDefault();
    applyJump();
  });
  jumpForm.dataset.jsReady = "true";
}

async function loadLog(id, template, signal) {
  try {
    const resp = await fetch(`/json/v1/log/${id}-${template}`, {
      signal,
    });
    if (!resp.ok) {
      return [null, `error: api returned with error code ${resp.status}`];
    }
    const data = await resp.json();
    return [data, null];
  } catch (err) {
    if (err.name == "AbortError") {
      return [null, null];
    } else if (err instanceof SyntaxError) {
      return [null, "error: invalid json returned from api"];
    } else {
      return [null, `error: ${err.message}`];
    }
  }
}

function logDialog(titleText, id, template) {
  const con = document.getElementById("log-dialog-container");
  const modal = con.querySelector(".dialog-box-container");
  const title = con.querySelector("#log-dialog-title");
  const body = con.querySelector(".dialog-content-inner");
  title.innerText = titleText;
  const dialog = new A11yDialog(con);
  const abort = new AbortController();
  dialog.on("show", async () => {
    disableBodyScroll(modal);

    const [data, err] = await loadLog(id, template, abort.signal);
    con.classList.add("dialog-loaded");
    announce("log loaded");
    if (err != null) {
      body.innerText = err;
      return;
    }
    replaceNodeContent(body, fmt_log(data));
  });
  dialog.on("hide", () => {
    // reset scroll lock, zero template, and cancel http requests
    enableBodyScroll(modal);
    con.classList.remove("dialog-loaded");
    title.innerText = "";
    body.replaceChildren();
    abort.abort();
  });
  dialog.show();
}

function wire_log_buttons() {
  const editor = document.querySelector(".schedule-editor");
  if (!editor) {
    return;
  }
  editor.addEventListener("click", (evt) => {
    const t = closestButtonWith(evt.target, "for");
    if (t == null) {
      return;
    }
    evt.preventDefault();
    const id = t.dataset["for"];
    if (!/\d+/.test(id)) {
      console.warn(["invalid data-for on log button", t]);
      return;
    }
    const tmpl = t.dataset["fromTemplate"];
    if (!/\d+/.test(tmpl)) {
      console.warn(["invalid data-from-template on log button", t]);
      return;
    }
    logDialog("history", id, tmpl);
  });
  editor
    .querySelectorAll("entry-cell button[data-for]")
    .forEach((e) => (e.hidden = false));
  editor.classList.add("js-log-buttons");
}

function wire_legend_modal() {
  const trigger = document.querySelector("#legend-open");
  const container = document.querySelector("#legend-dialog-container");
  if (!trigger || !container) {
    return;
  }
  const dialog = new A11yDialog(container);
  trigger.addEventListener("click", (evt) => {
    evt.preventDefault();
    dialog.show();
  });
}

function wire_inspector_modal() {
  const trigger = document.querySelector("#inspector-open");
  const container = document.querySelector("#inspector-dialog-container");
  if (!trigger || !container) {
    return;
  }
  const dialog = new A11yDialog(container);
  container.__schedulerInspectorDialog = dialog;
  trigger.addEventListener("click", (evt) => {
    evt.preventDefault();
    dialog.show();
  });
}

function format_inspector_error_rows(errors) {
  if (!Array.isArray(errors)) {
    return [];
  }
  return errors
    .map((err) => {
      if (!err) {
        return null;
      }
      if (
        typeof err.source == "string" &&
        err.source.length > 0 &&
        typeof err.message == "string" &&
        err.message.length > 0
      ) {
        return {
          source: err.source,
          message: err.message,
        };
      }
      const key = String(err.key || "");
      const src = key || "slot";
      let msg = "";
      switch (err.type) {
        case "revocation":
          msg = "you no longer have access to edit this device";
          break;
        case "expired":
          msg = "you missed the submission deadline";
          break;
        case "user-removed":
          msg = `you are no longer in ${key} ${err.value ?? ""}`;
          break;
        case "removed":
          msg = `${err.value ?? "entry value"} is no longer a valid ${key}`;
          break;
        case "overwrote":
          if (err.expected || err.expected === "") {
            const expected = err.expected
              ? String(err.expected)
              : "blank entry";
            const got = err.got ? String(err.got) : "blank entry";
            msg = `${key} overwritten by another user: expected ${expected} got ${got}`;
          } else {
            msg = `${key} was overwritten by another user`;
          }
          break;
        case "invalid":
          msg = err.value ? String(err.value) : "validation error";
          break;
        default:
          msg = err.msg ? String(err.msg) : "validation error";
      }
      return { source: src, message: msg };
    })
    .filter(Boolean);
}

function format_inspector_error_message(row) {
  const source = String(row?.source ?? "")
    .trim()
    .toLowerCase();
  const message = String(row?.message ?? "").trim() || "validation error";
  if (
    source == "" ||
    source == "slot" ||
    source == "server" ||
    source == "validator" ||
    source == "verifier"
  ) {
    return message;
  }
  if (message.toLowerCase().startsWith(`${source}:`)) {
    return message;
  }
  return `${source}: ${message}`;
}

function read_slot_validation_errors(entry) {
  if (!entry) {
    return [];
  }
  const out = [];
  const serverErrorRecord = serverErrorState.get(
    String(entry.dataset.id ?? ""),
  );
  const serverErrors =
    entry.dataset.serverErrors ??
    JSON.stringify(serverErrorRecord?.errors ?? null);
  if (serverErrors && serverErrors != "null") {
    try {
      const parsed = JSON.parse(serverErrors);
      const rows = Array.isArray(parsed)
        ? parsed
        : Array.isArray(parsed?.errors)
        ? parsed.errors
        : [];
      out.push(...format_inspector_error_rows(rows));
    } catch (_err) {
      out.push({
        source: "slot",
        message: "invalid server error payload",
      });
    }
  }
  const detail = entry.querySelector("entry-detail");
  if (!detail) {
    return out;
  }

  const controls = detail.querySelectorAll("input,select,textarea");
  for (const control of controls) {
    if (!(control instanceof HTMLElement)) {
      continue;
    }

    const controlId = control.getAttribute("id");
    const described = control.getAttribute("aria-describedby") ?? "";
    const errorTargets = described
      .split(" ")
      .map((s) => s.trim())
      .filter((s) => s.endsWith("-err"));

    let messages = [];
    for (const id of errorTargets) {
      const list = document.getElementById(id);
      if (!list) {
        continue;
      }
      for (const row of list.querySelectorAll("input-error")) {
        const txt = row.innerText?.trim();
        if (!txt) {
          continue;
        }
        messages.push(txt.replace(/^\W+/, ""));
      }
    }

    if (messages.length > 0 && controlId) {
      let source = "";
      const set = control.closest("input-set");
      if (set) {
        const label = set.querySelector("label");
        if (label) {
          source = label.innerText.trim();
        }
      }
      if (!source && controlId.includes("-")) {
        const chunks = controlId.split("-");
        source = chunks[0];
      }
      for (const message of messages) {
        out.push({ source: source || "slot", message });
      }
      messages = [];
    }

    if (control.matches("input[aria-invalid='true'],input:invalid")) {
      const message = control.validationMessage;
      if (message) {
        out.push({
          source: (() => {
            const set = control.closest("input-set");
            const label = set?.querySelector("label");
            if (label) {
              return label.innerText.trim();
            }
            return "slot";
          })(),
          message,
        });
      }
    }
  }

  if (entry.dataset.error == "true" && out.length == 0) {
    out.push({
      source: "slot",
      message: "entry is marked as erroring",
    });
  }
  const deduped = [];
  const seen = new Set();
  for (const row of out) {
    const source = String(row.source ?? "slot");
    const message = String(row.message ?? "validation error");
    const key = `${source}\u0000${message}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push({ source, message });
  }
  return deduped;
}

function sanitize_and_bind_inspector_editor(
  source,
  target,
  interactive,
  onSync,
) {
  if (!source || !target || !(source instanceof HTMLElement)) {
    return;
  }
  target.replaceChildren(source.cloneNode(true));
  const cloned = target.firstElementChild;
  if (!cloned) {
    return;
  }
  const controls = cloned.querySelectorAll(
    "input,select,textarea,button,fieldset",
  );
  const sourceControls = source.querySelectorAll(
    "input,select,textarea,button,fieldset",
  );
  const sourceLabels = source.querySelectorAll("label[for]");
  const idMap = new Map();
  const source_control_for = (cloneControl) => {
    const sourceId = cloneControl.dataset.sourceId;
    if (!sourceId) {
      return null;
    }
    const sourceControl = source.querySelector(`#${sourceId}`);
    if (!(sourceControl instanceof HTMLElement)) {
      return null;
    }
    return sourceControl;
  };
  const sync_mirrored_state = () => {
    for (const cloneControl of controls) {
      if (!(cloneControl instanceof HTMLElement)) {
        continue;
      }
      const sourceControl = source_control_for(cloneControl);
      if (!(sourceControl instanceof HTMLElement)) {
        continue;
      }

      if (cloneControl.disabled != sourceControl.disabled) {
        cloneControl.disabled = sourceControl.disabled;
      }

      if (
        cloneControl instanceof HTMLInputElement &&
        sourceControl instanceof HTMLInputElement
      ) {
        if (
          (cloneControl.type == "checkbox" || cloneControl.type == "radio") &&
          cloneControl.checked != sourceControl.checked
        ) {
          cloneControl.checked = sourceControl.checked;
        } else if (
          cloneControl.type != "checkbox" &&
          cloneControl.type != "radio" &&
          cloneControl.value != sourceControl.value &&
          document.activeElement !== cloneControl
        ) {
          cloneControl.value = sourceControl.value;
        }

        if (!sourceControl.hasAttribute("list")) {
          cloneControl.removeAttribute("list");
        } else {
          const sourceList = sourceControl.getAttribute("list") || "";
          if (sourceList == "") {
            cloneControl.removeAttribute("list");
          } else if (cloneControl.getAttribute("list") != sourceList) {
            cloneControl.setAttribute("list", sourceList);
          }
        }
        cloneControl.setCustomValidity(sourceControl.validationMessage || "");
        continue;
      }

      if (
        cloneControl instanceof HTMLSelectElement &&
        sourceControl instanceof HTMLSelectElement &&
        cloneControl.value != sourceControl.value &&
        document.activeElement !== cloneControl
      ) {
        cloneControl.value = sourceControl.value;
      }
      if (
        cloneControl instanceof HTMLTextAreaElement &&
        sourceControl instanceof HTMLTextAreaElement &&
        cloneControl.value != sourceControl.value &&
        document.activeElement !== cloneControl
      ) {
        cloneControl.value = sourceControl.value;
      }

      if (
        (cloneControl instanceof HTMLInputElement ||
          cloneControl instanceof HTMLSelectElement ||
          cloneControl instanceof HTMLTextAreaElement) &&
        (sourceControl instanceof HTMLInputElement ||
          sourceControl instanceof HTMLSelectElement ||
          sourceControl instanceof HTMLTextAreaElement)
      ) {
        cloneControl.setCustomValidity(sourceControl.validationMessage || "");
      }
    }
  };
  for (const sourceControl of sourceControls) {
    if (sourceControl.id) {
      idMap.set(sourceControl.id, `${sourceControl.id}-inspector`);
    }
  }
  for (const c of controls) {
    if (!(c instanceof HTMLElement)) {
      continue;
    }
    if (c.id) {
      c.dataset.sourceId = c.id;
      c.id = `${c.id}-inspector`;
    }
    if (c.matches("button")) {
      c.setAttribute("type", "button");
      if (!interactive) {
        c.disabled = true;
      }
    }
    if (c.matches("fieldset")) {
      const id = c.getAttribute("id");
      if (id) {
        c.id = `${id}-inspector`;
      }
      if (!interactive) {
        c.disabled = true;
      }
      continue;
    }
    if (c.matches("input") || c.matches("select") || c.matches("textarea")) {
      c.disabled = c.disabled || !interactive;
      if (interactive && c.type == "radio") {
        if (c.name) {
          c.name = `${c.name}-inspector`;
        }
      }
      if (!interactive) {
        c.setAttribute("tabindex", "-1");
      }
      if (!interactive) {
        continue;
      }
      c.addEventListener("input", () => {
        const sourceId = c.dataset.sourceId;
        if (!sourceId) {
          return;
        }
        const targetInput = source.querySelector(`#${sourceId}`);
        if (!targetInput || targetInput.disabled) {
          return;
        }
        const value = c.value;
        if (targetInput.type == "radio") {
          if (c.checked) {
            targetInput.checked = true;
          }
        } else if (targetInput.type == "checkbox") {
          targetInput.checked = c.checked;
        } else if (targetInput.value != value) {
          targetInput.value = value;
        }
        onSync?.(targetInput, c);
        targetInput.dispatchEvent(new Event("input", { bubbles: true }));
        sync_mirrored_state();
      });
      c.addEventListener("change", () => {
        const sourceId = c.dataset.sourceId;
        if (!sourceId) {
          return;
        }
        const targetInput = source.querySelector(`#${sourceId}`);
        if (!targetInput || targetInput.disabled) {
          return;
        }
        if (targetInput.type == "radio" && c.type == "radio") {
          targetInput.checked = c.checked;
          if (c.name) {
            const groupName = c.name.replace(/-inspector$/, "");
            source
              .querySelectorAll(`input[name="${groupName}"][type="radio"]`)
              .forEach((r) => {
                r.dispatchEvent(new Event("change", { bubbles: true }));
              });
          } else {
            targetInput.dispatchEvent(new Event("change", { bubbles: true }));
          }
        } else if (targetInput.type == "checkbox") {
          targetInput.checked = c.checked;
        } else {
          targetInput.value = c.value;
        }
        targetInput.dispatchEvent(new Event("change", { bubbles: true }));
        sync_mirrored_state();
      });
      c.addEventListener("list-change", () => {
        const sourceId = c.dataset.sourceId;
        if (!sourceId) {
          return;
        }
        const targetInput = source.querySelector(`#${sourceId}`);
        if (!targetInput) {
          return;
        }
        targetInput.setAttribute("list", c.getAttribute("list") || "none");
        targetInput.dispatchEvent(new Event("change", { bubbles: true }));
        sync_mirrored_state();
      });
    }
  }

  for (const sourceLabel of sourceLabels) {
    const forId = sourceLabel.getAttribute("for");
    if (!forId) {
      continue;
    }
    const targetLabel = cloned.querySelector(`label[for="${forId}"]`);
    if (!targetLabel) {
      continue;
    }
    const mappedId = idMap.get(forId);
    if (mappedId) {
      targetLabel.setAttribute("for", mappedId);
    }
  }

  if (interactive) {
    const reset = cloned.querySelector("button[data-reset]");
    if (reset && reset.dataset.sourceId == null) {
      const sourceReset = source.querySelector("button[data-reset]");
      if (sourceReset) {
        reset.dataset.sourceId = sourceReset.getAttribute("id") ?? "";
        reset.addEventListener("click", (evt) => {
          evt.preventDefault();
          sourceReset.click();
          window.setTimeout(() => {
            sanitize_and_bind_inspector_editor(
              source,
              target,
              interactive,
              onSync,
            );
          }, 0);
        });
      }
    }
    const logBtn = cloned.querySelector("button[data-for][data-from-template]");
    if (logBtn) {
      const sourceId = logBtn.getAttribute("data-for");
      const sourceFor = source
        .closest("entry-cell")
        ?.querySelector(`button[data-for="${sourceId}"]`);
      if (sourceFor) {
        logBtn.addEventListener("click", () => {
          sourceFor.click();
        });
      }
    }
  }

  sync_mirrored_state();
}

function wire_home_readonly_toggle() {
  const storageKey = "home.show-readonly-devices";
  const toggle = document.querySelector("#home-show-readonly");
  if (!toggle) {
    return;
  }
  let stored = null;
  try {
    stored = window.localStorage.getItem(storageKey);
  } catch (_err) {
    stored = null;
  }
  if (stored === "1" || stored === "0") {
    toggle.checked = stored === "1";
  }
  const readonlyRows = document.querySelectorAll(
    "[data-home-readonly-device=true]",
  );
  const sync = (persist = false) => {
    const showReadonly = Boolean(toggle.checked);
    readonlyRows.forEach((row) => {
      row.hidden = !showReadonly;
    });
    if (persist) {
      try {
        window.localStorage.setItem(storageKey, showReadonly ? "1" : "0");
      } catch (_err) {
        // ignore storage errors (for example private browsing restrictions)
      }
    }
  };
  sync();
  toggle.addEventListener("change", () => sync(true));
}

function wire_home_search_and_show_more() {
  const panels = document.querySelector(".home-panels");
  if (!panels) {
    return;
  }
  const readonlyToggle = document.querySelector("#home-show-readonly");
  const parseIntOr = (value, fallback) => {
    const num = Number.parseInt(value, 10);
    if (Number.isNaN(num) || num < 0) {
      return fallback;
    }
    return num;
  };
  const normalize = (text) =>
    String(text ?? "")
      .trim()
      .toLowerCase();
  const cfg = {
    debounceMs: parseIntOr(panels.dataset.homeFilterDebounceMs, 200),
    defaultVisible: parseIntOr(panels.dataset.homeDefaultVisible, 5),
    showMoreIncrement: parseIntOr(panels.dataset.homeShowMoreIncrement, 10),
    showMoreDelayMs: parseIntOr(panels.dataset.homeShowMoreDelayMs, 2000),
  };

  const stateForSection = (section) => {
    const sectionName = section.dataset.homeSection;
    const list = section.querySelector("ul[data-home-list]");
    if (!list) {
      return null;
    }
    const searchInput = document.querySelector(
      sectionName == "devices" ? "#home-device-search" : "#home-group-search",
    );
    const showMoreButton = document.querySelector(
      sectionName == "devices"
        ? "#home-devices-show-more"
        : "#home-groups-show-more",
    );
    return {
      section,
      list,
      sectionName,
      searchInput,
      showMoreButton,
      items: [...list.querySelectorAll("li[data-home-item]")],
      visibleCount: cfg.defaultVisible,
      filteredItems: [],
      filterTimer: null,
      showMoreTimer: null,
    };
  };

  const canShowReadonly = () => {
    return !readonlyToggle || Boolean(readonlyToggle.checked);
  };
  const sectionStates = [...document.querySelectorAll("[data-home-section]")]
    .map(stateForSection)
    .filter(Boolean);
  if (sectionStates.length == 0) {
    return;
  }

  const filterSection = (state) => {
    const query = normalize(state.searchInput?.value);
    const hasQuery = query.length >= 1;
    const showReadonly = canShowReadonly();

    state.filteredItems = [];
    for (const item of state.items) {
      if (
        state.sectionName == "devices" &&
        item.dataset.homeReadonlyDevice == "true"
      ) {
        if (!showReadonly) {
          continue;
        }
      }
      const name = normalize(item.dataset.homeItemName);
      if (hasQuery && !name.includes(query)) {
        continue;
      }
      state.filteredItems.push(item);
    }
    state.items.forEach((item) => {
      item.hidden = true;
    });
    const max = Math.max(0, state.visibleCount);
    state.filteredItems.slice(0, max).forEach((item) => {
      item.hidden = false;
    });
  };

  const applySection = (state, delayShowMore = false) => {
    filterSection(state);

    const showMore = state.filteredItems.length > state.visibleCount;
    if (!state.showMoreButton) {
      return;
    }
    state.showMoreButton.hidden = true;
    if (state.showMoreTimer) {
      clearTimeout(state.showMoreTimer);
      state.showMoreTimer = null;
    }
    if (delayShowMore) {
      state.showMoreTimer = window.setTimeout(() => {
        state.showMoreButton.hidden = !showMore;
        state.showMoreTimer = null;
      }, cfg.showMoreDelayMs);
    } else {
      state.showMoreButton.hidden = !showMore;
    }
  };

  const scheduleFilter = (state) => {
    state.visibleCount = cfg.defaultVisible;
    if (state.showMoreButton) {
      state.showMoreButton.hidden = true;
    }
    if (state.showMoreTimer) {
      clearTimeout(state.showMoreTimer);
      state.showMoreTimer = null;
    }
    if (state.filterTimer) {
      clearTimeout(state.filterTimer);
    }
    state.filterTimer = window.setTimeout(() => {
      state.filterTimer = null;
      applySection(state, true);
    }, cfg.debounceMs);
  };

  for (const state of sectionStates) {
    if (state.searchInput) {
      state.searchInput.addEventListener("input", () => {
        scheduleFilter(state);
      });
    }

    if (state.showMoreButton) {
      state.showMoreButton.addEventListener("click", (evt) => {
        evt.preventDefault();
        state.visibleCount += cfg.showMoreIncrement;
        applySection(state);
      });
    }
    applySection(state);
  }

  if (!readonlyToggle) {
    return;
  }
  readonlyToggle.addEventListener("change", () => {
    for (const state of sectionStates) {
      if (state.sectionName != "devices") {
        continue;
      }
      scheduleFilter(state);
    }
  });
}

class Grid {
  constructor(container, table, cells, onSelect = null) {
    this.container = container;
    this.table = table;
    this.cells = cells;
    this.onSelect = onSelect;
    const firstRow = this.firstVisibleRow();
    this.setRow(firstRow);
    this.setCol(firstRow >= 0 ? 0 : -1);
    this.setOpen(false);
  }
  findNextNonEmptyCol(direction, row = this.row()) {
    const targetRow = parseInt(row, 10);
    if (Number.isNaN(targetRow) || targetRow < 0 || targetRow > this.maxRow()) {
      return null;
    }
    if (targetRow != this.row()) {
      // if not current row, do not preselect hidden rows
      if (this.rowHidden(targetRow)) {
        return null;
      }
    }

    const startCol = this.col() + (direction < 0 ? -1 : 1);
    const walk = direction < 0 ? -1 : 1;
    for (let col = startCol; col >= 0 && col <= this.maxCol(); col += walk) {
      let found = false;
      for (let rowIndex = 0; rowIndex <= this.maxRow(); rowIndex += 1) {
        const rowCell = this.cells[rowIndex]?.[col];
        if (
          !rowCell ||
          rowCell.hidden ||
          !rowCell.querySelector("entry-cell")
        ) {
          continue;
        }
        if (!this.rowHidden(rowIndex)) {
          found = true;
          break;
        }
      }
      if (found) {
        return col;
      }
    }
    return null;
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
    const row = this.cells[this.row()];
    if (row == null) {
      return null;
    }
    return row[this.col()] ?? null;
  }
  rowHasCells(r) {
    const row = parseInt(r, 10);
    if (Number.isNaN(row)) {
      return false;
    }
    if (row < 0 || row > this.maxRow()) {
      return false;
    }
    return this.cells[row].length > 0;
  }
  rowHidden(r) {
    const row = parseInt(r, 10);
    // Rows with no cells are non-focusable and treated as hidden.
    if (!this.rowHasCells(row)) {
      return true;
    }
    // tr hidden when off hours and not toggled open.
    return this.cells[row][0].parentElement.hidden;
  }
  maxRow() {
    return this.cells.length - 1;
  }
  maxCol(r = this.row()) {
    const row = parseInt(r, 10);
    if (Number.isNaN(row)) {
      return -1;
    }
    if (row < 0 || row > this.maxRow()) {
      return -1;
    }
    for (let n = this.cells[row].length - 1; n >= 0; n -= 1) {
      const cell = this.cells[row][n];
      if (cell && !cell.hidden) {
        return n;
      }
    }
    return -1;
  }
  firstVisibleRow() {
    for (let n = 0; n <= this.maxRow(); n++) {
      if (!this.rowHidden(n)) {
        return n;
      }
    }
    return -1;
  }
  lastVisibleRow() {
    for (let n = this.maxRow(); n >= 0; n--) {
      if (!this.rowHidden(n)) {
        return n;
      }
    }
    return -1;
  }
  rowStart() {
    return this.focus(this.row(), 0);
  }
  rowEnd() {
    return this.focus(this.row(), this.maxCol());
  }
  moveCol(delta, { scroll = true } = {}) {
    const row = this.row();
    const nextCol = this.col() + delta;
    if (Number.isNaN(nextCol)) {
      return false;
    }
    return this.focus(row, Math.max(0, Math.min(this.maxCol(row), nextCol)), {
      scroll,
    });
  }
  colStart() {
    const row = this.firstVisibleRow();
    if (row < 0) {
      return false;
    }
    return this.focus(row, this.col());
  }
  colEnd() {
    const row = this.lastVisibleRow();
    if (row < 0) {
      return false;
    }
    return this.focus(row, this.col());
  }
  first() {
    const row = this.firstVisibleRow();
    if (row < 0) {
      return false;
    }
    return this.focus(row, 0);
  }
  last() {
    const row = this.lastVisibleRow();
    if (row < 0) {
      return false;
    }
    return this.focus(row, this.maxCol(row));
  }
  left() {
    return this.moveCol(-1, { scroll: false });
  }
  right() {
    return this.moveCol(1, { scroll: false });
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
    return this.focus(row, col, { scroll: false });
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
    return this.focus(row, col, { scroll: false });
  }
  select(row, col) {
    row = parseInt(row, 10);
    col = parseInt(col, 10);

    if (Number.isNaN(row) || Number.isNaN(col)) {
      return false;
    }

    // out of bounds, ignore
    if (row < 0 || row > this.maxRow()) {
      return false;
    }

    // if we're trying to select a hidden row,
    // arbitrarily select the first row that is not hidden.
    if (this.rowHidden(row)) {
      row = this.firstVisibleRow();
    }

    const maxCol = this.maxCol(row);
    if (row < 0 || col < 0 || maxCol < 0) {
      return false;
    }
    if (col > maxCol) {
      col = maxCol;
    }

    this.setRow(row);
    this.setCol(col);
    if (this.onSelect) {
      this.onSelect(row, col, this.selectedCell());
    }
    return true;
  }
  focus(row, col, { force = false, scroll = true } = {}) {
    if (!this.select(row, col)) {
      return false;
    }

    // skip if the cell already contains the cursor
    // unless force is specified which we use to handle ESC key
    const cell = this.selectedCell();
    if (cell == null) {
      return false;
    }
    if (!force && cell.matches(":focus-within")) {
      return false;
    }

    this.setOpen(false);
    cell.focus({
      preventScroll: true,
    });
    if (scroll) {
      this.scrollIntoView(row, col);
    }
    return true;
  }
  scrollIntoView(row, col) {
    if (!this.select(row, col)) {
      return;
    }
    const cell = this.selectedCell();
    if (cell == null) {
      return;
    }
    cell.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }
}

// focusables_around returns the focusable items immediately before and after elm.
// it is only designed to work on the editor pages.
function focusables_around(elm) {
  // note that this works because querySelectorAll returns elements in document order
  // and we know that there is always at least one focusable before and after elm
  let before = null;
  for (const f of document.querySelectorAll("a,button,input")) {
    if (f.matches(":disabled,[hidden]")) {
      continue;
    }
    if (f.closest('[aria-hidden="true"]')) {
      continue;
    }
    switch (elm.compareDocumentPosition(f)) {
      case Node.DOCUMENT_POSITION_PRECEDING:
        // the last time we set this will be the focusable directly before elm
        before = f;
        break;
      case Node.DOCUMENT_POSITION_FOLLOWING:
        return [before, f];
    }
  }
  return [before, before];
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
  const editor = container.querySelector(":scope>table");
  editor
    .querySelectorAll("entry-cell")
    .forEach((entry) => (entry.dataset.active = "false"));

  // create matrix indexing cells by (row, col)
  // and add extra attributes while we're in there
  const cells = [];
  editor.querySelectorAll("tbody tr").forEach((row) => {
    const i = cells.push([]) - 1;
    row.querySelectorAll("td").forEach((col) => {
      const j = cells[i].push(col) - 1;
      col.setAttribute("tabindex", "-1");
      col.setAttribute("role", "gridcell");
      col.dataset.row = i;
      col.dataset.col = j;
    });
  });

  let activeCell = null;
  const grid = new Grid(container, editor, cells, (row, col, selected) => {
    if (activeCell != null && activeCell !== selected) {
      const oldEntry = activeCell.querySelector("entry-cell");
      if (oldEntry) {
        oldEntry.dataset.active = "false";
      }
    }
    activeCell = selected;
    const entry = selected?.querySelector("entry-cell") ?? null;
    if (entry != null) {
      entry.dataset.active = "true";
    }
    editor.dispatchEvent(
      new CustomEvent("grid_selection", {
        bubbles: true,
        detail: { row, col, cell: selected, entry },
      }),
    );
  });
  editor.scheduleGrid = grid;
  const openInspectorFromGrid = () => {
    const inspectorOpen = document.querySelector("#inspector-open");
    if (inspectorOpen instanceof HTMLElement) {
      inspectorOpen.click();
      return true;
    }
    return false;
  };

  // we use these when handling tab from within the grid
  const [focusableBefore, focusableAfter] = focusables_around(container);

  // move focus to selected item in grid in the next microtask
  const focusContainer = () => {
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
  editor.querySelector("tbody").addEventListener("click", (evt) => {
    let t = evt.target;
    const setsInternalFocus = t.matches(
      ":is(input, button, label):not(:disabled)",
    );

    // if we're not a cell, see if we're in a cell
    if (!t.matches("td")) {
      t = t.closest("td");
    }
    if (t == null) {
      return;
    }

    const ds = t.dataset;
    grid.select(ds.row, ds.col);
    grid.setOpen(setsInternalFocus);
    grid.scrollIntoView(ds.row, ds.col);
  });

  editor.querySelector("tbody").addEventListener("dblclick", (evt) => {
    const cell = evt.target.closest("td");
    if (!cell) {
      return;
    }
    grid.select(cell.dataset.row, cell.dataset.col);
    if (openInspectorFromGrid()) {
      evt.preventDefault();
    }
  });

  // if we click inside the grid without changing focus,
  // focus the correct cell
  editor.addEventListener("click", (evt) => {
    const t = evt.target;
    if (t.matches("td")) {
      grid.focus(t.dataset.row, t.dataset.col);
      evt.preventDefault();
    }
  });

  const handleGridKeydown = (evt) => {
    if (evt.isComposing || evt.keyCode == 229) {
      return;
    }

    // if we're not in cell, we need to intercept all grid keys
    switch (evt.key) {
      case "Esc":
      case "Escape":
        if (grid.isOpen()) {
          grid.focus(...grid.pos(), true);
          break;
        }
        return;

      case "Left":
      case "ArrowLeft":
        if (!grid.left()) {
          emit_window_edge_shift(-1, grid.row(), grid.col(), "keyboard");
        }
        break;

      case "Right":
      case "ArrowRight":
        if (!grid.right()) {
          emit_window_edge_shift(1, grid.row(), grid.col(), "keyboard");
        }
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
        openInspectorFromGrid();
        break;

      case "Tab":
        if (grid.isOpen()) {
          // if we're in a cell, only need to worry about focus exiting the cell
          const t = evt.target;
          const selected = grid.selectedCell();
          if (selected == null) {
            return;
          }
          const [first, last] = edge_focusables(selected);
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
          } else {
            return;
          }
          break;
        }
        if (evt.shiftKey) {
          if (focusableBefore) {
            focusableBefore.focus();
          }
        } else if (focusableAfter) {
          focusableAfter.focus();
        }
        break;

      default:
        return;
    }
    evt.preventDefault();
  };

  container.addEventListener("keydown", handleGridKeydown);
  document.addEventListener(
    "keydown",
    (evt) => {
      if (evt.target instanceof HTMLElement) {
        const insideEditor = editor.contains(evt.target);
        if (insideEditor) {
          // grid-local handler already processes keys inside the editor.
          return;
        }
        const inGridCell = evt.target.closest("td");
        const outsideGridInput = evt.target.matches(
          "input, select, textarea, button, [contenteditable]",
        );
        const inJump = evt.target.closest("nav.jump-form");
        if (
          evt.target.closest(".dialog-container[aria-hidden='false']") ||
          inJump ||
          (outsideGridInput && !inGridCell)
        ) {
          return;
        }
      }
      handleGridKeydown(evt);
    },
    true,
  );
  grid.select(...grid.pos());
  editor.setAttribute("role", "grid");
  container.classList.add("js-grid");
}

function editor_dialog(
  save,
  showNotifications,
  titleText,
  content,
  then,
  options = {},
) {
  const con = document.getElementById("save-dialog-container");
  const modal = con.querySelector(".dialog-box-container");
  const title = con.querySelector("#save-dialog-title");
  const body = con.querySelector(".dialog-content-inner");
  const cancel = con.querySelector("button[name=cancel]");
  const confirm = con.querySelector("button[name=confirm]");
  const notificationsCon = con.querySelector(".dialog-form input-set");
  const notifications = notificationsCon.querySelector("#send-notifications");
  const defaultConfirmText =
    confirm.dataset.defaultText ?? confirm.innerText ?? "confirm";
  const defaultCancelText =
    cancel.dataset.defaultText ?? cancel.innerText ?? "cancel";
  confirm.dataset.defaultText = defaultConfirmText;
  cancel.dataset.defaultText = defaultCancelText;
  let confirmed = false;
  title.innerText = titleText;
  replaceNodeContent(body, content);
  confirm.innerText = options.confirmText ?? defaultConfirmText;
  cancel.innerText = options.cancelText ?? defaultCancelText;
  confirm.disabled = options.confirmDisabled === true;
  if (save) {
    cancel.hidden = false;
  }
  if (showNotifications) {
    notificationsCon.hidden = false;
    notifications.checked = true;
  }
  const dialog = new A11yDialog(con);
  dialog.on("show", () => {
    // scroll lock and focus cancel button
    disableBodyScroll(modal);
    confirmed = false;
    const focusTarget =
      !cancel.hidden && !cancel.disabled
        ? cancel
        : confirm.disabled
        ? null
        : confirm;
    focusTarget?.focus();
  });
  const markConfirmed = () => {
    confirmed = true;
  };
  const clearConfirmed = () => {
    confirmed = false;
  };
  confirm.onpointerdown = markConfirmed;
  confirm.onclick = markConfirmed;
  cancel.onpointerdown = clearConfirmed;
  cancel.onclick = clearConfirmed;
  dialog.on("hide", () => {
    enableBodyScroll(modal);
    if (confirmed && then) {
      then(notifications.checked);
    }
    // reset template
    title.innerText = "";
    body.replaceChildren();
    cancel.hidden = true;
    notificationsCon.hidden = true;
    notifications.checked = true;
    confirm.innerText = defaultConfirmText;
    cancel.innerText = defaultCancelText;
    confirm.disabled = false;
  });
  dialog.show();
}

function result_dialog(proc, options = {}) {
  const con = document.getElementById("result-dialog-container");
  const modal = con.querySelector(".dialog-box-container");
  const body = con.querySelector(".dialog-content-inner");
  const dialog = new A11yDialog(con);
  const abort = new AbortController();
  let changesSaved = false;
  let payload = null;
  let payloadMeta = {};
  const shouldReload = options.reload !== false;
  const onResolved = options.onResolved ?? null;
  const onSuccess = options.onSuccess ?? null;
  dialog.on("show", async () => {
    disableBodyScroll(modal);

    const [data, err, meta] = await proc(abort.signal);
    con.classList.add("dialog-loaded");
    announce("results available");
    if (err != null) {
      body.innerText = err;
      return;
    }
    replaceNodeContent(body, data);
    payload = data;
    payloadMeta = meta ?? {};
    if (meta && meta.saved !== undefined) {
      changesSaved = Boolean(meta.saved);
    } else {
      changesSaved = true;
    }
    if (changesSaved && typeof onResolved === "function") {
      onResolved(payload, payloadMeta);
    }
  });
  dialog.on("hide", () => {
    enableBodyScroll(modal);
    con.classList.remove("dialog-loaded");
    body.replaceChildren();
    abort.abort();
    if (changesSaved) {
      if (typeof onSuccess === "function") {
        onSuccess(payload, payloadMeta);
      }
      if (!shouldReload) {
        return;
      }
      // updates made, reload the page to refresh state
      // but first we need to disable our beforeunload handler
      // then scroll to the top of the page in case the browser saves
      // scroll position so it's clear what happened
      setBeforeUnload(false);
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
      location.reload();
    }
  });
  dialog.show();
}

// force elm to reprocess and report its validity to the css
function resetList(elm) {
  if (!elm) {
    return;
  }
  const listId = elm.list?.id || elm.getAttribute("list");
  if (!listId) {
    return;
  }
  elm.setAttribute("list", listId);
  const dl = get_datalists().get(listId);
  elm.setCustomValidity("");
  if (dl && elm.value) {
    const canon = dl.canonical.get(elm.value);
    if (!canon) {
      elm.setCustomValidity(dl.errorMessage);
    } else {
      elm.value = canon;
    }
  }
  elm.dispatchEvent(new CustomEvent("list-change"));
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

    this.requested = elm.querySelector(".requested");
    this.handler = elm.querySelector(".handler");

    const requestedOrig = to_bool(this.requested.dataset.orig);
    this.orig = {
      requested: requestedOrig,
      handler: requestedOrig ? this.handler.dataset.orig : "",
      subkind: "",
    };

    this.subkind_fieldset = elm.querySelector("fieldset"); // null if not tech
    this.subkind = null;
    if (this.kind == "tech") {
      // get the RadioNodeList of the radio group
      const radio = this.subkind_fieldset.querySelector("[type=radio]");
      this.subkind = radio.form.elements[radio.name];

      this.orig.subkind = this.subkind_fieldset.dataset.orig;
    }
    this.sync_controls();
  }
  get changed() {
    if (this.requested.checked != this.orig.requested) {
      return true;
    }
    // only check subkind if it exists and there is a request
    if (
      this.requested.checked &&
      this.subkind != null &&
      this.orig.subkind != this.subkind.value
    ) {
      return true;
    }
    return this.effective_handler != this.orig.handler;
  }
  get invalid() {
    // the handler is the only element that can be in an invalid state
    // but we only report it if it's something the user can fix
    return (
      this.requested.checked &&
      this.handler_editable &&
      !this.handler.validity.valid
    );
  }
  get request_active() {
    return Boolean(this.requested?.checked);
  }
  get response_window_open() {
    if (this.parent.locked) {
      return false;
    }
    // past entries are not editable (past handles users with edit_any)
    if (this.parent.past) {
      return false;
    }
    return true;
  }
  get request_editable() {
    if (!this.response_window_open) {
      return false;
    }
    // filing requests is controlled by the slot editability.
    return this.parent.bookingEditable;
  }
  get support_actionable() {
    const supportPerms = this.perms.support || {};
    const canFulfill =
      supportPerms[this.handler_permission_key] ??
      this.perms[this.handler_permission_key];
    return (
      this.response_window_open &&
      this.request_active &&
      canFulfill &&
      this.members.size > 0
    );
  }
  get editable() {
    return this.request_editable || this.support_actionable;
  }
  get handler_permission_key() {
    switch (this.kind) {
      case "med":
        return "medical";
      case "train":
        return "training";
      default:
        return this.kind;
    }
  }
  get handler_editable() {
    // assignment is constrained by role-specific permission, an active request,
    // and the current device roster.
    return this.support_actionable;
  }
  get effective_handler() {
    if (!this.handler) {
      return "";
    }
    return this.requested?.checked ? this.handler.value : "";
  }
  get subkind_editable() {
    return this.request_editable;
  }
  sync_controls() {
    if (this.requested) {
      this.requested.disabled = !this.request_editable;
    }
    this.elm.disabled = !this.editable;
    const requestActive = this.request_active;
    if (this.handler) {
      if (!requestActive && this.handler.value != "") {
        this.handler.value = "";
        resetList(this.handler);
      }
      this.handler.disabled = !requestActive || !this.handler_editable;
    }
    if (this.subkind_fieldset) {
      this.subkind_fieldset.disabled = !requestActive || !this.subkind_editable;
    }
    if (this.subkind) {
      this.subkind.disabled = !requestActive || !this.subkind_editable;
    }
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
    const handlerValue = this.effective_handler;
    if (handlerValue != this.orig.handler) {
      changes.handler = [this.orig.handler, handlerValue];
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
    resetList(this.handler);
    if (this.subkind != null) {
      this.subkind.value = this.orig.subkind;
    }
    this.sync_controls();
  }
}

class Cell {
  constructor(elm, cfg) {
    this.elm = elm;
    this.perms = cfg.perms;
    this.membership = cfg.membership;
    this.device_groups = cfg.device_groups;
    this.schedulable_groups = cfg.schedulable_groups;
    this.selection_group_list = cfg.selection_group_list;
    this.colors = cfg.colors;
    this.default_group = cfg.default_group ?? "";
    this.autofilled_group = false;

    // institute may be null depending on the page
    this.institute = elm.querySelector("input[id^=ins-]");
    this.group = elm.querySelector("input[id^=grp-]");
    this.member = elm.querySelector("input[id^=mem-]");
    this.legend = elm.querySelector("entry-legend");
    this.resetBtn = elm.querySelector("button[data-reset]");
    this.summaryKind = elm.dataset.summaryKind ?? "schedule";
    this.summaryPrimary = elm.querySelector(".entry-summary-primary");
    this.summarySecondary = elm.querySelector(".entry-summary-secondary");
    this.summaryTertiary = elm.querySelector(".entry-summary-tertiary");
    this.readonlyCue = elm.querySelector('[data-readonly-cue="slot"]');
    this.supportCue = elm.querySelector('[data-support-cue="slot"]');

    this.id = elm.dataset.id;

    // note that date is very different depending on the editor used
    this.hour = elm.dataset.hour;
    this.date = elm.dataset.date;

    // data-old is undefined in template editor so we simplify that to false.
    this.old = to_bool(elm.dataset.old) ?? false;

    // only set to true if this failed server side validation
    this.locked = false;

    this.orig = {
      institute: this.institute?.dataset.orig,
      group: this.group.dataset.orig,
      member: this.member.dataset.orig,
    };

    bind_datalist_validations(elm);

    // gather any support requests
    const subforms = [...elm.querySelectorAll("fieldset[data-sr]")];
    const kv = subforms.map((sr) => [
      sr.dataset.sr,
      new SupportRequestSubForm(sr, this, cfg),
    ]);
    this.sr = Object.fromEntries(kv);
    this.update_swatch();
    this.update_summary();

    // nothing further to do unless this cell has some actionable controls.
    if (!this.canInteract) {
      this.sync_state_flags();
      return;
    }

    if (this.editable && this.institute) {
      this.institute.disabled = false;
    }
    if (this.editable) {
      this.group.disabled = false;
      this.member.disabled = false;
      this.update_group_list();
      this.update_list();
    }

    for (const sr of Object.values(this.sr)) {
      sr.sync_controls();
    }

    this.elm.dataset.canEdit = this.editable;
    this.resetBtn.disabled = !this.canInteract;

    this.resetBtn.addEventListener("click", (evt) => {
      evt.preventDefault();
      this.reset();
      this.update();
    });
    this.elm.addEventListener("input", (evt) => {
      if (evt.target == this.group) {
        this.autofilled_group = false;
      }
      this.update();
    });
    this.member.addEventListener("list-change", () => {
      this.update();
    });
    this.elm.addEventListener("focusin", () => {
      this.preview_default_group();
    });
    this.elm.addEventListener("focusout", (evt) => {
      if (this.elm.contains(evt.relatedTarget)) {
        return;
      }
      this.clear_default_group();
    });
    this.sync_state_flags();
  }
  get member_changed() {
    return this.orig.member != this.member.value;
  }
  get group_changed() {
    return this.orig.group != this.group.value && !this.autofilled_group;
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
    return this.group_changed || this.member_changed;
  }
  get invalid() {
    if (!this.canInteract) {
      // cell state may be incorrect but the user can do nothing about it.
      return false;
    }
    if (
      "serverErrors" in this.elm.dataset ||
      serverErrorState.has(String(this.id))
    ) {
      return true;
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
  get past() {
    // users with edit_any are not bound by this concept
    if (this.perms.booking_edit_any) {
      return false;
    }
    return this.old;
  }
  get bookingEditable() {
    if (this.perms.booking_edit_any) {
      return true;
    }
    if (this.perms.booking_edit && !this.old) {
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
  get editable() {
    if (this.locked) {
      return false;
    }
    return this.bookingEditable;
  }
  get supportActionable() {
    return Object.values(this.sr).some((sr) => sr.support_actionable);
  }
  get canInteract() {
    return this.editable || this.supportActionable;
  }
  diff() {
    if (!this.changed) {
      return null;
    }
    // start off with the metadata
    const changes = {
      id: this.id,
      date: this.date,
      hour: this.hour,
    };
    if (this.institute && this.orig.institute != this.institute.value) {
      changes.institute = [this.orig.institute, this.institute.value];
    }
    if (this.group_changed || (this.autofilled_group && this.member_changed)) {
      changes.group = [this.orig.group, this.group.value];
    }
    if (this.member_changed) {
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
    this.autofilled_group = false;
    if (this.institute) {
      this.institute.value = this.orig.institute;
      resetList(this.institute);
    }
    this.group.value = this.orig.group;
    this.update_group_list();
    resetList(this.group);
    this.member.value = this.orig.member;
    this.update_list();
    resetList(this.member);
    for (const sr of Object.values(this.sr)) {
      sr.reset();
    }
    this.update_summary();
    this.fire_change();
  }
  update_group_list() {
    let list = this.selection_group_list;
    const special =
      ["training", "maint"].includes(this.orig.group) ||
      ["training", "maint"].includes(this.group.value);
    if (!list || this.perms.edit_any || special) {
      list = "groups";
    }
    const currentListId =
      this.group.list?.id || this.group.getAttribute("list");
    if (currentListId != list) {
      this.group.setAttribute("list", list);
    }
  }
  update_list() {
    const gv = this.group.value;
    let list = "none"; // special list always empty to simplify checks
    // group has members, update list to point to appropriate datalist.
    if (this.schedulable_groups.has(gv)) {
      list = `members-of-${gv}`;
    }
    // only update the list if it's different than the current value
    // to avoid unnecessary revalidation
    const currentListId =
      this.member.list?.id || this.member.getAttribute("list");
    if (currentListId != list) {
      this.member.setAttribute("list", list);
      resetList(this.member);
    }
  }
  update_swatch() {
    if (!this.legend) {
      return;
    }
    const classPrefix = "swatch-group-";
    for (const cls of [...this.legend.classList]) {
      if (cls.startsWith(classPrefix)) {
        this.legend.classList.remove(cls);
      }
    }
    const displayGroup =
      this.autofilled_group && !this.member_changed ? "" : this.group.value;
    const token = this.colors[displayGroup] ? cssToken(displayGroup) : "none";
    this.legend.classList.add(`${classPrefix}${token}`);
    this.legend.style.setProperty(
      "--swatch",
      this.colors[displayGroup] || "transparent",
    );
  }
  update_summary() {
    if (
      !this.summaryPrimary &&
      !this.summarySecondary &&
      !this.summaryTertiary
    ) {
      return;
    }
    const displayGroup =
      this.autofilled_group && !this.member_changed ? "" : this.group.value;
    const group = displayGroup || "open";
    const member = this.member.value || "unassigned";
    if (this.summaryPrimary) {
      this.summaryPrimary.innerText = group;
    }
    if (this.summarySecondary) {
      this.summarySecondary.innerText = member;
    }

    if (this.summaryTertiary) {
      if (this.summaryKind == "template") {
        const institute = this.institute?.value || "none";
        this.summaryTertiary.innerText = `institute: ${institute}`;
      } else {
        const support = [];
        if (this.sr.tech?.requested.checked) {
          support.push("tech");
        }
        if (this.sr.train?.requested.checked) {
          support.push("training");
        }
        if (this.sr.med?.requested.checked) {
          support.push("medical");
        }
        if (support.length > 0) {
          this.summaryTertiary.innerText = `support: ${support.join(", ")}`;
        } else {
          this.summaryTertiary.innerText = "no support requests";
        }
      }
    }

    const tooltip = [`group: ${group}`, `member: ${member}`];
    if (this.summaryKind == "template") {
      tooltip.push(`institute: ${this.institute?.value || "none"}`);
    } else {
      tooltip.push(this.summaryTertiary?.innerText || "no support requests");
    }
    this.elm.title = tooltip.join("; ");
  }
  preview_default_group() {
    if (!this.default_group || !this.bookingEditable) {
      return;
    }
    if (this.orig.group != "" || this.group.value != "") {
      return;
    }
    this.group.value = this.default_group;
    this.autofilled_group = true;
    this.update_group_list();
    this.update_list();
    this.update_swatch();
    this.update_summary();
    this.sync_state_flags();
  }
  clear_default_group() {
    if (!this.autofilled_group || this.member_changed) {
      return;
    }
    this.group.value = this.orig.group;
    this.autofilled_group = false;
    this.update_group_list();
    this.update();
  }
  fire_change() {
    this.elm.dispatchEvent(
      new CustomEvent("cell_change", {
        bubbles: true,
        detail: this,
      }),
    );
  }
  sync_state_flags() {
    this.elm.dataset.canEdit = from_bool(this.editable);
    this.elm.dataset.bookingEditable = from_bool(this.bookingEditable);
    this.elm.dataset.canInteract = from_bool(this.canInteract);
    this.elm.dataset.supportActionable = from_bool(this.supportActionable);
    this.elm.dataset.changed = from_bool(this.changed);
    this.elm.dataset.error = from_bool(this.invalid);
    if (this.readonlyCue) {
      this.readonlyCue.hidden = this.bookingEditable;
    }
    if (this.supportCue) {
      this.supportCue.hidden = !this.supportActionable;
    }
  }
  update() {
    this.update_group_list();
    this.update_list();
    this.update_swatch();
    for (const sr of Object.values(this.sr)) {
      sr.sync_controls();
    }
    this.update_summary();
    this.sync_state_flags();
    this.fire_change();
  }
  resetAndLock() {
    // this cell was submitted to and rejected by the server
    // reset it to default state and prevent further changes
    this.reset();
    this.locked = true;
    this.elm.dataset.canEdit = false;
    this.elm.dataset.canInteract = false;
    this.elm.dataset.supportActionable = false;
    this.elm.dataset.locked = "true";

    if (this.institute) {
      this.institute.disabled = true;
    }
    this.group.disabled = true;
    this.member.disabled = true;
    this.resetBtn.disabled = true;
    for (const sr of Object.values(this.sr)) {
      sr.elm.disabled = true;
    }
    this.sync_state_flags();
  }
}

function json_from_script_or(id, def) {
  const script = document.querySelector(
    'script[type="application/json"]#' + id,
  );
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
  const dl = document.querySelector("datalist#" + id);
  if (!dl) {
    return def;
  }
  return [...dl.options].map((opt) => opt.value);
}
function wire_cell_editors() {
  const scrollContainer = document.querySelector(".editor #scroll-container");
  const container = scrollContainer?.querySelector("tbody");
  if (container == null) {
    return;
  }
  const editor = scrollContainer.querySelector(":scope>table");
  const form = document.querySelector("form.editor");
  const templateEditor = form.classList.contains("template-editor");
  const scheduleLoad = json_from_script_or("schedule-load-config", null);
  const remoteScheduleRows =
    scheduleLoad != null &&
    typeof scheduleLoad.endpoint == "string" &&
    typeof scheduleLoad.start == "string";
  const initialWindowDays = Number.parseInt(scheduleLoad?.days, 10) || 7;
  const scheduleWindow = remoteScheduleRows
    ? {
        start: parse_ymd(scheduleLoad.start),
        requestedDays: initialWindowDays,
        chunkDays: initialWindowDays,
        totalDays: initialWindowDays,
        endpoint: scheduleLoad.endpoint,
      }
    : {
        start: null,
        requestedDays: 0,
        chunkDays: 7,
        totalDays: 0,
        endpoint: "",
      };
  if (
    Number.isNaN(scheduleWindow.requestedDays) ||
    scheduleWindow.requestedDays < 1
  ) {
    scheduleWindow.requestedDays = 7;
  }
  scheduleWindow.requestedDays = Math.min(
    31,
    Math.max(1, scheduleWindow.requestedDays),
  );
  scheduleWindow.totalDays = scheduleWindow.requestedDays;
  scheduleWindow.chunkDays = scheduleWindow.requestedDays;

  const nextDayEndpoint = scheduleWindow.endpoint
    ? scheduleWindow.endpoint.replace("/schedule-rows", "/schedule-next-day")
    : "";
  const jumpPrevDayBtn = document.querySelector("#jump-prev-non-empty");
  const jumpNextDayBtn = document.querySelector("#jump-next-non-empty");
  const scrollPrevDayBtn = form.querySelector("#scroll-prev-day");
  const scrollNextDayBtn = form.querySelector("#scroll-next-day");
  const jumpNav = document.querySelector("nav.jump-form");
  const inspectorBar = form.querySelector(".editor-inspector");
  const topNav = document.querySelector(".top");
  const subpageNav = document.querySelector(".subpage-nav");

  // if this is missing, we're on a template page so everything is true
  const perms = json_from_script_or("user-perms", {
    booking_edit: true,
    booking_edit_any: true,
    support_fulfillment: {
      medical: true,
      tech: true,
      training: true,
    },
    edit: true,
    edit_any: true,
    medical: true,
    tech: true,
    training: true,
  });
  const normalizedPerms = {
    booking_edit: Boolean(perms.booking_edit ?? perms.edit),
    booking_edit_any: Boolean(perms.booking_edit_any ?? perms.edit_any),
    support: {
      tech: Boolean(perms.support_fulfillment?.tech ?? perms.tech),
      medical: Boolean(perms.support_fulfillment?.medical ?? perms.medical),
      training: Boolean(perms.support_fulfillment?.training ?? perms.training),
    },
  };
  normalizedPerms.edit = normalizedPerms.booking_edit;
  normalizedPerms.edit_any = normalizedPerms.booking_edit_any;
  normalizedPerms.tech = normalizedPerms.support.tech;
  normalizedPerms.medical = normalizedPerms.support.medical;
  normalizedPerms.training = normalizedPerms.support.training;

  // if this is missing we're on a template page so edit_any is true and it's irrelevant
  const user_groups = json_from_script_or("user-groups", []);
  const membership = new Set(user_groups);
  membership.add(""); // consider every one a member of the null group

  const device_groups = new Set(json_from_script_or("device-groups", []));
  const colors = json_from_script_or("group-colors", {});
  const human_hours = json_from_script_or("human-hours", null);
  const offHours = new Set(
    json_from_script_or("schedule-off-hours", []).map((hour) => String(hour)),
  );
  const selectionGroups = datalist_ids_or("selection-groups", []);

  const tech_members = new Set(datalist_ids_or("tech", []));
  const train_members = new Set(datalist_ids_or("train", []));
  const med_members = new Set(datalist_ids_or("med", []));

  // get a set of all group names for groups that have member lists
  const schedulable_groups = new Set(
    [...document.querySelectorAll("datalist[id^=members-of-]")].map((elm) =>
      elm.id.slice("members-of-".length),
    ),
  );

  const cfg = {
    perms: normalizedPerms,
    membership,
    device_groups,
    schedulable_groups,
    default_group:
      !normalizedPerms.booking_edit_any && selectionGroups.length == 1
        ? selectionGroups[0]
        : "",
    selection_group_list: document.querySelector("datalist#selection-groups")
      ? "selection-groups"
      : "groups",
    colors,
    sr_members: {
      tech: tech_members,
      train: train_members,
      med: med_members,
    },
  };

  // keep track of changed and invalid cells
  const cells = new Map();
  const changed = new Set();
  const any_changed = () => Boolean(changed.size);
  const invalid = new Set();
  const any_invalid = () => Boolean(invalid.size);
  const changedInvalid = new Set();
  serverErrorState.clear();

  // keep caption in sync with cell updates
  const caption = document.querySelector("#caption");
  const update_caption = (which, bool) => {
    if (!caption) {
      return;
    }
    caption.dataset[which] = from_bool(bool);
  };
  const inspectorState = {
    target: "Select a time slot",
    summary: "no slot selected",
    mode: "Read-only booking",
    pending: "0 changes",
    errors: "0 errors",
  };
  const inspector = {
    barTarget: document.querySelector(".editor-inspector-target"),
    detailTarget: document.querySelector(".editor-inspector-detail-target"),
    detailSummary: document.querySelector(".editor-inspector-detail-summary"),
    detailMode: document.querySelector(".editor-inspector-detail-mode"),
    detailPending: document.querySelector(".editor-inspector-detail-pending"),
    detailErrors: document.querySelector(".editor-inspector-detail-errors"),
    open: document.querySelector("#inspector-open"),
    openSupportCue: document.querySelector(
      '#inspector-open [data-support-cue="selection"]',
    ),
    openReadonlyCue: document.querySelector(
      '#inspector-open [data-readonly-cue="selection"]',
    ),
    review: document.querySelector("#review-pending"),
    save: document.querySelector("#inspector-save"),
    errorList: document.querySelector("#inspector-error-list"),
    slotEditor: document.querySelector("#inspector-slot-editor"),
    durationRoot: document.querySelector("#inspector-duration"),
    durationButtons: [
      ...document.querySelectorAll("#inspector-duration [data-duration-slots]"),
    ],
    endTimeSelect: document.querySelector("#inspector-end-slot"),
    previewStart: document.querySelector("#inspector-preview-start"),
    previewEnd: document.querySelector("#inspector-preview-end"),
    previewCount: document.querySelector("#inspector-preview-count"),
  };
  const inspectorContainer = document.querySelector(
    "#inspector-dialog-container",
  );
  const inspectorDialog =
    document.querySelector("#inspector-dialog-container")
      ?.__schedulerInspectorDialog ?? null;
  const inspectorDialogOpen = () =>
    Boolean(
      activeEntry &&
        inspectorContainer &&
        inspector.slotEditor &&
        inspector.slotEditor.hidden === false,
    );
  const set_inspector_action_label = (
    bookingEditable,
    supportActionable,
    selected = false,
  ) => {
    if (!inspector.open) {
      return;
    }
    const label = inspector.open.querySelector(".legend-toggle-label");
    if (!label) {
      return;
    }
    label.innerText = "Details";
    if (inspector.openSupportCue) {
      inspector.openSupportCue.hidden = !selected || !supportActionable;
    }
    if (inspector.openReadonlyCue) {
      inspector.openReadonlyCue.hidden = !selected || bookingEditable;
    }
    inspector.open.dataset.editMode = selected
      ? bookingEditable
        ? "editable"
        : "readonly"
      : "none";
    const buttonTitle =
      selected && !bookingEditable && supportActionable
        ? "Open selection details for a read-only slot with actionable support"
        : selected && !bookingEditable
        ? "Open selection details for a read-only slot"
        : "Open selection details";
    inspector.open.title = buttonTitle;
  };
  const render_slot_errors = (rows) => {
    inspectorState.errors = `${rows.length} error${
      rows.length == 1 ? "" : "s"
    }`;
    if (!inspector.errorList) {
      sync_inspector_modal();
      return;
    }
    inspector.errorList.replaceChildren();
    if (rows.length == 0) {
      inspector.errorList.hidden = true;
      sync_inspector_modal();
      return;
    }
    for (const row of rows) {
      const item = document.createElement("li");
      item.textContent = format_inspector_error_message(row);
      inspector.errorList.append(item);
    }
    inspector.errorList.hidden = false;
    sync_inspector_modal();
  };
  const sync_inspector_modal = () => {
    if (inspector.barTarget) {
      inspector.barTarget.innerText = inspectorState.target;
    }
    if (inspector.detailTarget) {
      inspector.detailTarget.innerText = inspectorState.target;
    }
    if (inspector.detailSummary) {
      inspector.detailSummary.innerText = inspectorState.summary;
    }
    if (inspector.detailMode) {
      inspector.detailMode.innerText = inspectorState.mode;
    }
    if (inspector.detailPending) {
      inspector.detailPending.innerText = inspectorState.pending;
    }
    if (inspector.detailErrors) {
      inspector.detailErrors.innerText = inspectorState.errors;
    }
  };
  const loadStatus = document.querySelector("#editor-load-status");
  const rows = [...container.querySelectorAll("tr[data-hour]")];
  const rowsByHour = new Map(rows.map((row) => [row.dataset.hour, row]));
  for (const row of rows) {
    row.dataset.offHour = offHours.has(String(row.dataset.hour))
      ? "true"
      : "false";
  }
  let queue_floating_header_sync = () => {};
  let queue_placeholder_shadow_sync = () => {};
  let loadErrorMessage = "";
  const is_slot_visibly_empty = (entry, cell) => {
    if (!entry) {
      return false;
    }
    if (
      entry.dataset.changed == "true" ||
      entry.dataset.error == "true" ||
      "serverErrors" in entry.dataset
    ) {
      return false;
    }
    const entryId = String(entry.dataset.id ?? "");
    const resolvedCell =
      cell ?? (entryId != "" ? cells.get(entryId) ?? null : null);
    if (resolvedCell) {
      if (resolvedCell.changed || resolvedCell.invalid || resolvedCell.locked) {
        return false;
      }
      const hasGroup = String(resolvedCell.group?.value ?? "").trim() != "";
      const hasMember = String(resolvedCell.member?.value ?? "").trim() != "";
      const hasSupport = Object.values(resolvedCell.sr ?? {}).some((sr) =>
        Boolean(sr.requested?.checked),
      );
      return !hasGroup && !hasMember && !hasSupport;
    }

    const group = String(
      entry.querySelector("input[id^=grp-]")?.value ?? "",
    ).trim();
    const member = String(
      entry.querySelector("input[id^=mem-]")?.value ?? "",
    ).trim();
    const hasSupport = [
      ...entry.querySelectorAll("fieldset[data-sr] .requested"),
    ]
      .filter((elm) => elm instanceof HTMLInputElement)
      .some((elm) => elm.checked);
    return group == "" && member == "" && !hasSupport;
  };
  const sync_slot_empty_state = (entry, cell = null) => {
    if (!(entry instanceof HTMLElement)) {
      return false;
    }
    const empty = is_slot_visibly_empty(entry, cell);
    entry.dataset.empty = from_bool(empty);
    const hostCell = entry.closest("td");
    if (hostCell instanceof HTMLTableCellElement) {
      hostCell.dataset.empty = from_bool(empty);
    }
    return empty;
  };
  const sync_row_visibility = () => {
    for (const row of rows) {
      const slots = [...row.querySelectorAll("td")].slice(
        0,
        scheduleWindow.totalDays,
      );
      for (const td of slots) {
        const entry = td.querySelector("entry-cell");
        if (!entry) {
          delete td.dataset.empty;
          continue;
        }
        sync_slot_empty_state(entry);
      }
    }
    queue_floating_header_sync();
    queue_placeholder_shadow_sync();
  };
  const tableHeadRow = scrollContainer.querySelector("thead tr");
  const HEADER_PREVIEW_OVERSCAN_COLS = remoteScheduleRows ? 2 : 0;
  const append_header_preview_columns = (count = 0) => {
    if (!(tableHeadRow instanceof HTMLTableRowElement)) {
      return;
    }
    const safeCount = Math.max(0, Number.parseInt(String(count ?? 0), 10) || 0);
    if (safeCount == 0) {
      return;
    }
    for (let i = 0; i < safeCount; i += 1) {
      const th = document.createElement("th");
      th.hidden = true;
      th.dataset.bufferCol = "true";
      tableHeadRow.append(th);
      for (const row of rows) {
        const td = document.createElement("td");
        td.hidden = true;
        td.dataset.bufferCol = "true";
        row.append(td);
      }
    }
  };
  const baseRenderedDayColumns =
    tableHeadRow instanceof HTMLTableRowElement
      ? Math.max(1, tableHeadRow.querySelectorAll("th").length)
      : 1;
  append_header_preview_columns(HEADER_PREVIEW_OVERSCAN_COLS);
  const headerCells = [
    ...scrollContainer.querySelectorAll("thead th:not(:first-child)"),
  ];
  const scrollShell = scrollContainer.closest(".editor-scroll-shell");
  const MAX_RENDERED_DAY_COLUMNS = Math.max(1, headerCells.length);
  const MAX_REQUESTED_DAY_COLUMNS = Math.max(1, baseRenderedDayColumns);
  const MIN_VISIBLE_DAY_COLUMN_PX = 144;
  const MIN_LEADING_COLUMN_PX = 56;
  const MAX_LEADING_COLUMN_PX = 96;
  const DEFAULT_LEADING_COLUMN_PX = 72;
  let lockedLeadingColumnWidthPx = 0;
  let headerTranslatePx = 0;
  let headerPreviewOffsetPx = 0;
  let headerSettleTimer = 0;
  let headerSettleInFlight = false;
  let movementSkeletonActive = false;
  let floatingHeader = null;
  let floatingHeaderTable = null;
  let floatingHeaderCells = [];
  if (
    scrollShell instanceof HTMLElement &&
    tableHeadRow instanceof HTMLTableRowElement
  ) {
    floatingHeader = document.createElement("div");
    floatingHeader.className = "editor-floating-header";
    floatingHeader.hidden = true;
    floatingHeader.setAttribute("aria-hidden", "true");

    floatingHeaderTable = document.createElement("table");
    floatingHeaderTable.className = "editor-floating-header-table";
    const floatingHead = document.createElement("thead");
    floatingHead.append(tableHeadRow.cloneNode(true));
    floatingHeaderTable.append(floatingHead);
    floatingHeader.append(floatingHeaderTable);
    scrollShell.append(floatingHeader);
    floatingHeaderCells = [
      ...floatingHeader.querySelectorAll("thead th:not(:first-child)"),
    ];
  }
  const clamp_requested_days = (days) => {
    const parsed = Number.parseInt(days, 10);
    if (Number.isNaN(parsed)) {
      return 1;
    }
    return Math.min(MAX_REQUESTED_DAY_COLUMNS, Math.max(1, parsed));
  };
  if (!remoteScheduleRows) {
    scheduleWindow.requestedDays = MAX_RENDERED_DAY_COLUMNS;
    scheduleWindow.totalDays = MAX_RENDERED_DAY_COLUMNS;
  }
  scheduleWindow.requestedDays = clamp_requested_days(
    scheduleWindow.requestedDays,
  );
  const clamp_leading_width_px = (value) => {
    if (!Number.isFinite(value) || value <= 0) {
      return DEFAULT_LEADING_COLUMN_PX;
    }
    return Math.min(
      MAX_LEADING_COLUMN_PX,
      Math.max(MIN_LEADING_COLUMN_PX, Math.round(value)),
    );
  };
  const measured_leading_width_px = () => {
    const firstRowLead = rows[0]?.querySelector("th");
    const sources = [firstRowLead, tableHeadRow?.children?.[0]];
    for (const source of sources) {
      if (!(source instanceof HTMLElement)) {
        continue;
      }
      const width = source.getBoundingClientRect().width;
      if (Number.isFinite(width) && width > 0) {
        return width;
      }
    }
    return DEFAULT_LEADING_COLUMN_PX;
  };
  const leading_column_width_px = ({ refresh = false } = {}) => {
    if (refresh || lockedLeadingColumnWidthPx <= 0) {
      lockedLeadingColumnWidthPx = clamp_leading_width_px(
        measured_leading_width_px(),
      );
    }
    return lockedLeadingColumnWidthPx;
  };
  const compute_visible_day_count = (
    requestedDays = scheduleWindow.requestedDays,
  ) => {
    const requested = clamp_requested_days(requestedDays);
    if (!remoteScheduleRows) {
      return MAX_RENDERED_DAY_COLUMNS;
    }
    if (scrollContainer.clientWidth <= 0) {
      return requested;
    }
    const available = Math.max(
      0,
      scrollContainer.clientWidth - leading_column_width_px() - 2,
    );
    const fit = Math.max(1, Math.floor(available / MIN_VISIBLE_DAY_COLUMN_PX));
    return Math.max(1, Math.min(requested, fit));
  };
  const apply_visible_day_layout = ({
    requestedDays = scheduleWindow.requestedDays,
  } = {}) => {
    const previousDays = Math.max(1, scheduleWindow.totalDays || 1);
    scheduleWindow.requestedDays = clamp_requested_days(requestedDays);
    const nextDays = compute_visible_day_count(scheduleWindow.requestedDays);
    scheduleWindow.totalDays = nextDays;
    scheduleWindow.chunkDays = Math.min(31, Math.max(1, nextDays));
    const leadingWidthPx = Math.max(
      MIN_LEADING_COLUMN_PX,
      Math.round(leading_column_width_px()),
    );
    const leadingWidthText = `${leadingWidthPx}px`;
    if (tableHeadRow instanceof HTMLTableRowElement) {
      const leadingCell = tableHeadRow.children[0];
      if (leadingCell instanceof HTMLElement) {
        leadingCell.style.width = leadingWidthText;
        leadingCell.style.minWidth = leadingWidthText;
        leadingCell.style.maxWidth = leadingWidthText;
      }
    }
    for (const row of rows) {
      const leadingCell = row.querySelector("th");
      if (!(leadingCell instanceof HTMLElement)) {
        continue;
      }
      leadingCell.style.width = leadingWidthText;
      leadingCell.style.minWidth = leadingWidthText;
      leadingCell.style.maxWidth = leadingWidthText;
    }

    const available = Math.max(
      1,
      scrollContainer.clientWidth - leadingWidthPx - 2,
    );
    const dayWidthPx = Math.max(
      96,
      Math.floor(available / scheduleWindow.totalDays),
    );
    const widthText = `${dayWidthPx}px`;

    const sync_day_cell = (cell, visible) => {
      if (!(cell instanceof HTMLElement)) {
        return;
      }
      cell.hidden = !visible;
      if (!visible) {
        cell.style.width = "";
        cell.style.minWidth = "";
        cell.style.maxWidth = "";
        return;
      }
      cell.style.width = widthText;
      cell.style.minWidth = widthText;
      cell.style.maxWidth = widthText;
    };

    for (let col = 0; col < MAX_RENDERED_DAY_COLUMNS; col += 1) {
      const visible = col < scheduleWindow.totalDays;
      sync_day_cell(headerCells[col], visible);
      sync_day_cell(floatingHeaderCells[col], visible);
      for (const row of rows) {
        const td = row.querySelectorAll("td")[col];
        sync_day_cell(td, visible);
      }
    }
    scrollContainer.scrollLeft = 0;

    const grid = editor.scheduleGrid;
    if (grid) {
      const maxVisibleCol = Math.max(0, scheduleWindow.totalDays - 1);
      if (Number.isInteger(grid.col()) && grid.col() > maxVisibleCol) {
        grid.select(grid.row(), maxVisibleCol);
      }
    }

    return {
      changed: nextDays != previousDays,
      grew: nextDays > previousDays,
      previousDays,
      nextDays,
    };
  };
  const HEADER_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const HEADER_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const formatHeaderLabel = (date) => {
    if (!(date instanceof Date)) {
      return "";
    }
    const weekday = HEADER_WEEKDAYS[date.getUTCDay()] ?? "";
    const month = HEADER_MONTHS[date.getUTCMonth()] ?? "";
    const day = String(date.getUTCDate()).padStart(2, "0");
    return `${weekday} (${month}-${day})`;
  };
  const startDate = () => {
    if (scheduleWindow.start == null) {
      return null;
    }
    return scheduleWindow.start;
  };
  const visibleEndDate = () => {
    const first = startDate();
    if (first == null) {
      return null;
    }
    return add_days(first, scheduleWindow.totalDays - 1);
  };
  const dateForCol = (col) => {
    const parsed = Number.parseInt(col, 10);
    if (Number.isNaN(parsed)) {
      return null;
    }
    const first = startDate();
    if (first == null) {
      return null;
    }
    return add_days(first, parsed);
  };

  const syncHeaderDates = ({
    dayOffset = 0,
    translatePx = 0,
    leadingOverscanCols = 0,
    trailingOverscanCols = 0,
    columnWidthPx = 0,
  } = {}) => {
    const first = startDate();
    if (tableHeadRow instanceof HTMLTableRowElement) {
      tableHeadRow.style.transform =
        translatePx == 0 ? "" : `translateX(${Math.round(translatePx)}px)`;
    }
    headerTranslatePx = translatePx;
    if (first == null) {
      return;
    }
    const availableOverscan = Math.max(
      0,
      MAX_RENDERED_DAY_COLUMNS - scheduleWindow.totalDays,
    );
    const safeLeadingOverscan = Math.max(
      0,
      Math.min(
        availableOverscan,
        Number.parseInt(String(leadingOverscanCols ?? 0), 10) || 0,
      ),
    );
    const safeTrailingOverscan = Math.max(
      0,
      Math.min(
        availableOverscan - safeLeadingOverscan,
        Number.parseInt(String(trailingOverscanCols ?? 0), 10) || 0,
      ),
    );
    const visibleHeaders = Math.max(
      1,
      Math.min(
        MAX_RENDERED_DAY_COLUMNS,
        scheduleWindow.totalDays + safeLeadingOverscan + safeTrailingOverscan,
      ),
    );
    for (const cellSet of [headerCells, floatingHeaderCells]) {
      for (let i = 0; i < cellSet.length; i += 1) {
        const visible = i < visibleHeaders;
        const th = cellSet[i];
        if (!th) {
          continue;
        }
        th.hidden = !visible;
        if (!visible) {
          th.removeAttribute("data-date");
          th.innerText = "";
          if (th.dataset.bufferCol == "true") {
            th.style.width = "";
            th.style.minWidth = "";
            th.style.maxWidth = "";
          }
          continue;
        }
        const date = add_days(first, i + dayOffset - safeLeadingOverscan);
        th.innerText = formatHeaderLabel(date);
        th.dataset.date = ymd(date);
        if (i >= scheduleWindow.totalDays && columnWidthPx > 0) {
          const px = `${Math.round(columnWidthPx)}px`;
          th.style.width = px;
          th.style.minWidth = px;
          th.style.maxWidth = px;
        }
      }
    }
    queue_floating_header_sync();
  };

  apply_visible_day_layout();
  syncHeaderDates();
  const parse_root_px_var = (name) => {
    const value = window
      .getComputedStyle(document.documentElement)
      .getPropertyValue(name);
    const parsed = Number.parseFloat(value);
    if (!Number.isFinite(parsed)) {
      return 0;
    }
    return parsed;
  };
  const sticky_header_top_px = () => {
    return (
      parse_root_px_var("--scheduler-sticky-top") +
      parse_root_px_var("--scheduler-jump-height") +
      parse_root_px_var("--scheduler-inspector-height") +
      8
    );
  };
  let floatingHeaderSyncHandle = 0;
  const sync_floating_header = () => {
    const set_header_reserve = (height) => {
      if (!(scrollShell instanceof HTMLElement)) {
        return;
      }
      scrollShell.style.setProperty(
        "--floating-header-reserve",
        `${Math.max(0, Math.round(height))}px`,
      );
    };
    const set_edge_button_layout = (
      visible,
      { top = 0, shellRect = null } = {},
    ) => {
      const buttons = [scrollPrevDayBtn, scrollNextDayBtn].filter(
        (button) => button instanceof HTMLButtonElement,
      );
      if (buttons.length == 0) {
        return;
      }
      for (const button of buttons) {
        button.style.position = "fixed";
      }
      if (!visible || !(shellRect instanceof DOMRect)) {
        for (const button of buttons) {
          button.style.opacity = "0";
          button.style.pointerEvents = "none";
        }
        return;
      }
      const topPx = Math.max(0, Math.round(top));
      const leftPx = Math.max(6, Math.round(shellRect.left + 6));
      const rightPx = Math.max(
        6,
        Math.round(window.innerWidth - shellRect.right + 6),
      );
      if (scrollPrevDayBtn instanceof HTMLButtonElement) {
        scrollPrevDayBtn.style.top = `${topPx}px`;
        scrollPrevDayBtn.style.left = `${leftPx}px`;
        scrollPrevDayBtn.style.right = "auto";
        scrollPrevDayBtn.style.opacity = "1";
        scrollPrevDayBtn.style.pointerEvents = "";
      }
      if (scrollNextDayBtn instanceof HTMLButtonElement) {
        scrollNextDayBtn.style.top = `${topPx}px`;
        scrollNextDayBtn.style.right = `${rightPx}px`;
        scrollNextDayBtn.style.left = "auto";
        scrollNextDayBtn.style.opacity = "1";
        scrollNextDayBtn.style.pointerEvents = "";
      }
    };
    if (
      !(floatingHeader instanceof HTMLElement) ||
      !(floatingHeaderTable instanceof HTMLTableElement) ||
      !(tableHeadRow instanceof HTMLTableRowElement)
    ) {
      set_header_reserve(0);
      set_edge_button_layout(false);
      return;
    }
    const sourceCells = [...tableHeadRow.children];
    const targetCells = [
      ...floatingHeaderTable.querySelectorAll("thead tr > :is(th, td)"),
    ];
    if (sourceCells.length == 0 || sourceCells.length != targetCells.length) {
      floatingHeader.hidden = true;
      set_header_reserve(0);
      set_edge_button_layout(false);
      return;
    }
    const stickyTop = sticky_header_top_px();
    const shellRect = scrollContainer.getBoundingClientRect();
    const tableRect = editor.getBoundingClientRect();
    const headerRect = tableHeadRow.getBoundingClientRect();
    const visible =
      shellRect.top <= stickyTop &&
      tableRect.bottom > stickyTop + Math.max(1, headerRect.height);
    const controlsVisible =
      tableRect.bottom > 0 &&
      shellRect.top < window.innerHeight &&
      shellRect.width > 0;
    const controlsTop = visible
      ? stickyTop + headerRect.height + 6
      : shellRect.top + headerRect.height + 6;
    set_edge_button_layout(controlsVisible, {
      top: controlsTop,
      shellRect,
    });
    floatingHeader.hidden = !visible;
    if (!visible) {
      set_header_reserve(0);
      return;
    }
    set_header_reserve(headerRect.height);

    floatingHeader.style.top = `${Math.round(stickyTop)}px`;
    floatingHeader.style.left = `${Math.round(shellRect.left)}px`;
    floatingHeader.style.width = `${Math.round(shellRect.width)}px`;
    floatingHeader.style.height = `${Math.ceil(headerRect.height)}px`;

    const tableWidth = Math.max(editor.scrollWidth, shellRect.width);
    floatingHeaderTable.style.width = `${Math.round(tableWidth)}px`;
    floatingHeaderTable.style.transform = `translateX(${Math.round(
      -scrollContainer.scrollLeft + headerTranslatePx,
    )}px)`;

    for (let i = 0; i < sourceCells.length; i += 1) {
      const sourceCell = sourceCells[i];
      const targetCell = targetCells[i];
      if (!sourceCell || !targetCell) {
        continue;
      }
      targetCell.hidden = sourceCell.hidden;
      if (sourceCell.hidden) {
        continue;
      }
      const width = sourceCell.getBoundingClientRect().width;
      if (!Number.isFinite(width) || width <= 0) {
        continue;
      }
      const px = `${Math.round(width)}px`;
      targetCell.style.width = px;
      targetCell.style.minWidth = px;
      targetCell.style.maxWidth = px;
      targetCell.textContent = sourceCell.textContent;
    }
  };
  queue_floating_header_sync = () => {
    if (floatingHeaderSyncHandle != 0) {
      return;
    }
    floatingHeaderSyncHandle = window.requestAnimationFrame(() => {
      floatingHeaderSyncHandle = 0;
      sync_floating_header();
    });
  };
  const update_sticky_offsets = () => {
    let topOffset = 8;
    if (
      topNav instanceof HTMLElement &&
      window.getComputedStyle(topNav).position == "sticky"
    ) {
      topOffset += Math.round(topNav.getBoundingClientRect().height);
    }
    if (
      subpageNav instanceof HTMLElement &&
      window.getComputedStyle(subpageNav).position == "sticky"
    ) {
      topOffset += Math.round(subpageNav.getBoundingClientRect().height);
    }
    document.documentElement.style.setProperty(
      "--scheduler-sticky-top",
      `${Math.max(0, topOffset)}px`,
    );
    const jumpHeight =
      jumpNav instanceof HTMLElement &&
      window.getComputedStyle(jumpNav).position == "sticky"
        ? Math.round(jumpNav.getBoundingClientRect().height)
        : 0;
    document.documentElement.style.setProperty(
      "--scheduler-jump-height",
      `${Math.max(0, jumpHeight)}px`,
    );
    const inspectorHeight =
      inspectorBar instanceof HTMLElement &&
      window.getComputedStyle(inspectorBar).position == "sticky"
        ? Math.round(inspectorBar.getBoundingClientRect().height)
        : 0;
    document.documentElement.style.setProperty(
      "--scheduler-inspector-height",
      `${Math.max(0, inspectorHeight)}px`,
    );
    queue_floating_header_sync();
  };
  update_sticky_offsets();
  window.addEventListener("resize", update_sticky_offsets, { passive: true });
  window.addEventListener("resize", queue_placeholder_shadow_sync, {
    passive: true,
  });
  window.addEventListener("scroll", queue_floating_header_sync, {
    passive: true,
  });
  window.addEventListener("scroll", queue_placeholder_shadow_sync, {
    passive: true,
  });
  scrollContainer.addEventListener("scroll", queue_floating_header_sync, {
    passive: true,
  });
  if ("ResizeObserver" in window) {
    const stickyObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(() => {
        update_sticky_offsets();
        queue_floating_header_sync();
      });
    });
    if (topNav instanceof HTMLElement) {
      stickyObserver.observe(topNav);
    }
    if (subpageNav instanceof HTMLElement) {
      stickyObserver.observe(subpageNav);
    }
    if (jumpNav instanceof HTMLElement) {
      stickyObserver.observe(jumpNav);
    }
    if (inspectorBar instanceof HTMLElement) {
      stickyObserver.observe(inspectorBar);
    }
    stickyObserver.observe(scrollContainer);
    stickyObserver.observe(editor);
  }

  const dayLabelForCol = (col) => {
    const date = dateForCol(col);
    if (date == null) {
      return "";
    }
    return formatHeaderLabel(date);
  };
  const hasHorizontalOverflow = () => {
    return scrollContainer.scrollWidth > scrollContainer.clientWidth + 1;
  };
  const atLeftEdge = () => {
    return scrollContainer.scrollLeft <= 1;
  };
  const atRightEdge = () => {
    return (
      scrollContainer.scrollLeft + scrollContainer.clientWidth >=
      scrollContainer.scrollWidth - 1
    );
  };
  const oneDayScrollAmount = () => {
    const firstCell = scrollContainer.querySelector("tbody td:not([hidden])");
    const fallback = Math.max(
      160,
      Math.round(scrollContainer.clientWidth * 0.25),
    );
    if (!firstCell) {
      return fallback;
    }
    const width = firstCell.getBoundingClientRect().width;
    if (!Number.isFinite(width) || width <= 0) {
      return fallback;
    }
    return Math.max(120, Math.round(width + 4));
  };
  const visible_day_column_width_px = () => {
    for (const header of headerCells) {
      if (!(header instanceof HTMLElement) || header.hidden) {
        continue;
      }
      const width = header.getBoundingClientRect().width;
      if (Number.isFinite(width) && width > 0) {
        return width;
      }
    }
    return Math.max(1, oneDayScrollAmount());
  };
  const compute_header_preview_overscan = () => {
    const available = Math.max(
      0,
      MAX_RENDERED_DAY_COLUMNS - scheduleWindow.totalDays,
    );
    if (available <= 0) {
      return { leading: 0, trailing: 0 };
    }
    if (available == 1) {
      if (headerPreviewOffsetPx > 0) {
        return { leading: 0, trailing: 1 };
      }
      return { leading: 1, trailing: 0 };
    }
    return { leading: 1, trailing: 1 };
  };
  const sync_preview_body_columns = ({
    visibleCols = scheduleWindow.totalDays,
    columnWidthPx = 0,
  } = {}) => {
    if (!remoteScheduleRows) {
      return;
    }
    const safeVisibleCols = Math.max(
      1,
      Math.min(
        MAX_RENDERED_DAY_COLUMNS,
        Number.parseInt(String(visibleCols ?? scheduleWindow.totalDays), 10) ||
          scheduleWindow.totalDays,
      ),
    );
    const widthText =
      columnWidthPx > 0 ? `${Math.max(1, Math.round(columnWidthPx))}px` : "";
    for (let col = 0; col < MAX_RENDERED_DAY_COLUMNS; col += 1) {
      const visible = col < safeVisibleCols;
      for (const row of rows) {
        const td = row.querySelectorAll("td")[col];
        if (!(td instanceof HTMLElement)) {
          continue;
        }
        td.hidden = !visible;
        if (!visible) {
          td.style.width = "";
          td.style.minWidth = "";
          td.style.maxWidth = "";
          continue;
        }
        if (widthText == "") {
          continue;
        }
        td.style.width = widthText;
        td.style.minWidth = widthText;
        td.style.maxWidth = widthText;
      }
    }
  };
  const apply_header_preview = () => {
    if (!remoteScheduleRows) {
      return;
    }
    const colWidth = Math.max(1, visible_day_column_width_px());
    const dayOffset = Math.trunc(headerPreviewOffsetPx / colWidth);
    const remainderPx = headerPreviewOffsetPx - dayOffset * colWidth;
    const overscan = compute_header_preview_overscan();
    syncHeaderDates({
      dayOffset,
      translatePx: -remainderPx - overscan.leading * colWidth,
      leadingOverscanCols: overscan.leading,
      trailingOverscanCols: overscan.trailing,
      columnWidthPx: colWidth,
    });
    sync_preview_body_columns({
      visibleCols:
        scheduleWindow.totalDays + overscan.leading + overscan.trailing,
      columnWidthPx: colWidth,
    });
  };
  const clear_header_preview = () => {
    headerPreviewOffsetPx = 0;
    sync_preview_body_columns({
      visibleCols: scheduleWindow.totalDays,
    });
    syncHeaderDates();
  };
  const clear_header_settle_timer = () => {
    if (headerSettleTimer == 0) {
      return;
    }
    window.clearTimeout(headerSettleTimer);
    headerSettleTimer = 0;
  };
  const updateEdgeScrollButtons = () => {
    if (remoteScheduleRows) {
      if (scrollPrevDayBtn) {
        scrollPrevDayBtn.disabled = false;
      }
      if (scrollNextDayBtn) {
        scrollNextDayBtn.disabled = false;
      }
      return;
    }
    const overflow = hasHorizontalOverflow();
    if (scrollPrevDayBtn) {
      scrollPrevDayBtn.disabled = !overflow || atLeftEdge();
    }
    if (scrollNextDayBtn) {
      scrollNextDayBtn.disabled = !overflow || atRightEdge();
    }
  };
  const row_is_in_viewport = (row, margin = 48) => {
    if (!(row instanceof HTMLTableRowElement)) {
      return false;
    }
    const rect = row.getBoundingClientRect();
    return rect.bottom >= -margin && rect.top <= window.innerHeight + margin;
  };
  const build_slot_placeholder = ({ shadow = false } = {}) => {
    const placeholder = document.createElement("div");
    placeholder.className = shadow
      ? "slot-placeholder slot-skeleton"
      : "slot-placeholder";
    placeholder.setAttribute("aria-hidden", "true");
    return placeholder;
  };
  const reset_row_placeholders = (row, { shadow = false } = {}) => {
    row.querySelectorAll("td:not([data-buffer-col='true'])").forEach((cell) => {
      cell.dataset.placeholder = "true";
      cell.replaceChildren(build_slot_placeholder({ shadow }));
    });
  };
  const reset_window_placeholders = () => {
    for (const row of rows) {
      reset_row_placeholders(row, { shadow: row_is_in_viewport(row) });
    }
  };
  const sync_placeholder_shadow = () => {
    for (const row of rows) {
      const shadow = row_is_in_viewport(row);
      row
        .querySelectorAll("td[data-placeholder='true'] > .slot-placeholder")
        .forEach((elm) => {
          elm.classList.toggle("slot-skeleton", shadow);
        });
    }
  };
  let placeholderShadowSyncHandle = 0;
  queue_placeholder_shadow_sync = () => {
    if (placeholderShadowSyncHandle != 0) {
      return;
    }
    placeholderShadowSyncHandle = window.requestAnimationFrame(() => {
      placeholderShadowSyncHandle = 0;
      sync_placeholder_shadow();
    });
  };
  const displayed_rows_for_hydration = () => {
    const visibleRows = rows.filter((row) => row_is_in_viewport(row));
    if (visibleRows.length > 0) {
      return visibleRows;
    }
    return rows.slice(0, 6);
  };
  const is_entry_booking_editable = (entry) =>
    Boolean(
      entry &&
        (entry.dataset.bookingEditable ?? entry.dataset.canEdit) == "true",
    );
  const is_entry_editable = (entry) =>
    Boolean(
      entry &&
        is_entry_booking_editable(entry) &&
        entry.dataset.locked != "true",
    );
  const is_entry_interactive = (entry) =>
    Boolean(
      entry &&
        entry.dataset.canInteract == "true" &&
        entry.dataset.locked != "true",
    );
  const is_entry_support_actionable = (entry) =>
    Boolean(entry && entry.dataset.supportActionable == "true");
  let activeEntry = null;
  let selectionVersion = 0;
  let modalDurationSlots = 1;
  let modalTargetEntries = [];
  let modalDurationAnchorKey = null;
  const durationDraftSnapshots = new Map();

  for (const row of rows) {
    if (!remoteScheduleRows || row.querySelector("entry-cell")) {
      row.dataset.loaded = "true";
    } else {
      row.dataset.loaded = "false";
      reset_row_placeholders(row, { shadow: row_is_in_viewport(row) });
    }
  }

  const readSelectedErrors = (entry) =>
    entry ? read_slot_validation_errors(entry) : [];
  const duration_anchor_key = (entry) =>
    entry ? `${entry.dataset.date ?? ""}:${entry.dataset.hour ?? ""}` : null;
  const compareCellsChronologically = (a, b) => {
    if (a.date < b.date) {
      return -1;
    }
    if (a.date > b.date) {
      return 1;
    }
    const hourA = Number.parseInt(String(a.hour), 10);
    const hourB = Number.parseInt(String(b.hour), 10);
    if (hourA < hourB) {
      return -1;
    }
    if (hourA > hourB) {
      return 1;
    }
    return 0;
  };
  const sorted_cells_chronologically = (cellsToSort) =>
    [...cellsToSort].sort(compareCellsChronologically);
  const sorted_changed_cells = () => sorted_cells_chronologically(changed);
  const sorted_invalid_cells = () => sorted_cells_chronologically(invalid);
  const slot_summary = (entry) => {
    if (!entry) {
      return "no slot selected";
    }
    const primary =
      entry.querySelector(".entry-summary-primary")?.innerText ?? "open";
    const secondary =
      entry.querySelector(".entry-summary-secondary")?.innerText ??
      "unassigned";
    const tertiary = entry.querySelector(".entry-summary-tertiary")?.innerText;
    const pieces = [primary, secondary];
    if (tertiary) {
      pieces.push(tertiary);
    }
    return pieces.join(" | ");
  };
  const review_issue_count = () => invalid.size;
  const collect_review_issues = () =>
    sorted_invalid_cells()
      .map((cell) => {
        const errors = readSelectedErrors(cell.elm);
        if (errors.length == 0) {
          return null;
        }
        return {
          cell,
          label: slot_label(cell.elm),
          summary: slot_summary(cell.elm),
          errors,
        };
      })
      .filter(Boolean);
  const build_review_content = (issues, diffs, { blocking = false } = {}) => {
    const out = document.createDocumentFragment();
    const addSection = (titleText) => {
      const section = document.createElement("section");
      section.className = "review-section";
      const heading = document.createElement("h2");
      heading.textContent = titleText;
      section.append(heading);
      out.append(section);
      return section;
    };

    if (issues.length > 0) {
      const issueSection = addSection(
        issues.length == 1 ? "Active issue" : "Active issues",
      );
      const intro = document.createElement("p");
      intro.textContent = blocking
        ? "Resolve these issues before submitting the pending changes."
        : "Use this list to match the active error markers in the schedule.";
      issueSection.append(intro);
      const list = document.createElement("dl");
      list.className = "review-issue-list";
      for (const issue of issues) {
        const slotRow = document.createElement("dt");
        slotRow.textContent = issue.label;
        list.append(slotRow);
        const summaryRow = document.createElement("dd");
        summaryRow.className = "review-issue-summary";
        summaryRow.textContent = issue.summary;
        list.append(summaryRow);
        for (const row of issue.errors) {
          const detailRow = document.createElement("dd");
          detailRow.textContent = format_inspector_error_message(row);
          list.append(detailRow);
        }
      }
      issueSection.append(list);
    }

    if (diffs.length > 0) {
      const changeSection = addSection("Pending changes");
      const [, summary] = fmt_editor_diffs(human_hours, templateEditor, diffs);
      changeSection.append(summary);
    }

    if (issues.length == 0 && diffs.length == 0) {
      const empty = document.createElement("p");
      empty.textContent = "There are no pending changes or active issues.";
      out.append(empty);
    }
    return out;
  };
  const update_pending_review_control = () => {
    if (!inspector.review) {
      return;
    }
    const total = changed.size;
    const invalidCount = review_issue_count();
    inspector.review.disabled = total == 0 && invalidCount == 0;
    inspector.review.dataset.pendingCount = String(total);
    inspector.review.dataset.invalidCount = String(invalidCount);
    const label = inspector.review.querySelector(".legend-toggle-label");
    if (label) {
      label.innerText = `Review pending (${total})`;
    }
    inspector.review.setAttribute(
      "aria-label",
      total > 0 && invalidCount > 0
        ? `review ${total} pending change${
            total == 1 ? "" : "s"
          } and ${invalidCount} active error${invalidCount == 1 ? "" : "s"}`
        : total > 0
        ? `review ${total} pending change${total == 1 ? "" : "s"}`
        : invalidCount > 0
        ? `review ${invalidCount} active error${invalidCount == 1 ? "" : "s"}`
        : "review pending changes",
    );
  };
  const inspector_target_entries = (entry) => {
    if (!entry) {
      return [];
    }
    if (entry == activeEntry && modalTargetEntries.length > 0) {
      return modalTargetEntries;
    }
    return [entry];
  };
  const inspector_target_cells = (entry, fallbackCell = null) => {
    const targets = inspector_target_entries(entry)
      .map((target) => ensure_cell(target))
      .filter((targetCell) => targetCell);
    if (targets.length > 0) {
      return targets;
    }
    return fallbackCell ? [fallbackCell] : [];
  };
  const readInspectorErrors = (entry) =>
    inspector_target_entries(entry).flatMap((target) =>
      readSelectedErrors(target),
    );
  const update_inspector_counts = (entry, cell, slotErrors = null) => {
    const changes = inspector_target_cells(entry, cell).filter(
      (targetCell) => targetCell.changed,
    ).length;
    inspectorState.pending = `${changes} change${changes == 1 ? "" : "s"}`;
    const errors = Array.isArray(slotErrors)
      ? slotErrors
      : readInspectorErrors(entry);
    render_slot_errors(errors);
    sync_inspector_modal();
    return { changes, slotErrors: errors };
  };
  const slot_label = (entry) => {
    if (!entry) {
      return "not selected";
    }
    const date = humanize_date_if_needed(entry.dataset.date ?? "");
    const hour = human_hours?.[entry.dataset.hour] ?? entry.dataset.hour ?? "";
    return `${date}, ${hour}`.replace(/^,\s*/, "");
  };
  const collect_chronological_entries = () => {
    const ordered = [];
    for (let col = 0; col < scheduleWindow.totalDays; col += 1) {
      for (const row of rows) {
        const td = row.querySelectorAll("td")[col];
        if (!td) {
          continue;
        }
        const entry = td.querySelector("entry-cell");
        if (entry) {
          ordered.push(entry);
        }
      }
    }
    return ordered;
  };
  const resolve_duration_targets = (anchorEntry, count = 1) => {
    if (!anchorEntry) {
      return [];
    }
    const ordered = collect_chronological_entries();
    const anchorIndex = ordered.findIndex(
      (candidate) => candidate == anchorEntry,
    );
    if (anchorIndex < 0) {
      return [];
    }
    const maxCount = Math.max(1, ordered.length - anchorIndex);
    const safeCount = Math.max(1, Math.min(maxCount, Number(count) || 1));
    return ordered.slice(anchorIndex, anchorIndex + safeCount);
  };
  const sync_duration_preview = (targets) => {
    const list = Array.isArray(targets) ? targets : [];
    const anchor = list[0] ?? null;
    const tail = list[list.length - 1] ?? null;
    if (inspector.previewStart) {
      inspector.previewStart.innerText = slot_label(anchor);
    }
    if (inspector.previewEnd) {
      inspector.previewEnd.innerText = slot_label(tail ?? anchor);
    }
    if (inspector.previewCount) {
      inspector.previewCount.innerText = `${list.length} slot${
        list.length == 1 ? "" : "s"
      }`;
    }
  };
  function snapshotCellValues(cell) {
    const out = {
      institute: cell.institute?.value ?? "",
      group:
        cell.autofilled_group && !cell.member_changed
          ? ""
          : cell.group?.value ?? "",
      member: cell.member?.value ?? "",
      sr: {},
    };
    for (const [kind, sr] of Object.entries(cell.sr)) {
      const requested = Boolean(sr.requested?.checked);
      out.sr[kind] = {
        requested,
        handler: requested ? sr.handler?.value ?? "" : "",
        subkind: sr.subkind ? sr.subkind.value : "",
      };
    }
    return out;
  }
  function sameCellValues(left, right) {
    if (!left || !right) {
      return false;
    }
    if ((left.institute ?? "") != (right.institute ?? "")) {
      return false;
    }
    if ((left.group ?? "") != (right.group ?? "")) {
      return false;
    }
    if ((left.member ?? "") != (right.member ?? "")) {
      return false;
    }
    const kinds = new Set([
      ...Object.keys(left.sr ?? {}),
      ...Object.keys(right.sr ?? {}),
    ]);
    for (const kind of kinds) {
      const lhs = left.sr?.[kind] ?? {};
      const rhs = right.sr?.[kind] ?? {};
      if (Boolean(lhs.requested) != Boolean(rhs.requested)) {
        return false;
      }
      if ((lhs.handler ?? "") != (rhs.handler ?? "")) {
        return false;
      }
      if ((lhs.subkind ?? "") != (rhs.subkind ?? "")) {
        return false;
      }
    }
    return true;
  }
  function syncCellValues(cell, values) {
    if (!cell || !values) {
      return;
    }
    const preserveServerErrors =
      "serverErrors" in cell.elm.dataset &&
      sameCellValues(snapshotCellValues(cell), values);
    if (preserveServerErrors) {
      cell.preserveServerErrors = true;
    }
    try {
      applyValuesToCell(cell, values);
    } finally {
      delete cell.preserveServerErrors;
    }
  }
  function restoreDurationDraftSnapshots(nextIds = new Set()) {
    for (const [cellId, values] of [...durationDraftSnapshots.entries()]) {
      if (nextIds.has(cellId)) {
        continue;
      }
      const cell = cells.get(String(cellId));
      durationDraftSnapshots.delete(cellId);
      if (!cell) {
        continue;
      }
      syncCellValues(cell, values);
    }
  }
  function syncDurationDraftTargets({ finalize = false } = {}) {
    if (templateEditor || !activeEntry) {
      if (finalize) {
        durationDraftSnapshots.clear();
      } else {
        restoreDurationDraftSnapshots();
      }
      return;
    }
    const anchorCell = ensure_cell(activeEntry);
    if (!anchorCell) {
      if (finalize) {
        durationDraftSnapshots.clear();
      } else {
        restoreDurationDraftSnapshots();
      }
      return;
    }
    const targets = resolve_duration_targets(activeEntry, modalDurationSlots)
      .map((entry) => ensure_cell(entry))
      .filter((cell) => cell && cell.id != anchorCell.id);
    const nextIds = new Set(targets.map((cell) => String(cell.id)));
    if (!finalize) {
      restoreDurationDraftSnapshots(nextIds);
    }
    const anchorValues = snapshotCellValues(anchorCell);
    for (const cell of targets) {
      if (!durationDraftSnapshots.has(cell.id)) {
        durationDraftSnapshots.set(cell.id, snapshotCellValues(cell));
      }
      syncCellValues(cell, anchorValues);
    }
    if (activeEntry == anchorCell.elm) {
      update_inspector_counts(activeEntry, anchorCell);
    }
    if (finalize) {
      durationDraftSnapshots.clear();
    }
  }
  const sync_duration_controls = (entry, editable) => {
    if (!inspector.durationRoot) {
      return;
    }
    const target = entry ?? activeEntry;
    if (!target) {
      modalDurationSlots = 1;
      modalTargetEntries = [];
      modalDurationAnchorKey = null;
      inspector.durationRoot.hidden = true;
      sync_duration_preview([]);
      return;
    }
    inspector.durationRoot.hidden = false;
    const nextAnchorKey = duration_anchor_key(target);
    if (nextAnchorKey !== modalDurationAnchorKey) {
      modalDurationSlots = 1;
      modalDurationAnchorKey = nextAnchorKey;
    }
    const ordered = collect_chronological_entries();
    const anchorIndex = ordered.findIndex((candidate) => candidate == target);
    const maxSlots =
      anchorIndex < 0 ? 1 : Math.max(1, ordered.length - anchorIndex);
    modalDurationSlots = Math.max(1, Math.min(maxSlots, modalDurationSlots));
    modalTargetEntries = resolve_duration_targets(target, modalDurationSlots);
    if (inspector.endTimeSelect) {
      inspector.endTimeSelect.replaceChildren();
      for (let count = 1; count <= maxSlots; count += 1) {
        const option = document.createElement("option");
        const targets = resolve_duration_targets(target, count);
        const tail = targets[targets.length - 1] ?? target;
        option.value = String(count);
        option.textContent = `${slot_label(tail)} (${count} slot${
          count == 1 ? "" : "s"
        })`;
        if (count == modalDurationSlots) {
          option.selected = true;
        }
        inspector.endTimeSelect.append(option);
      }
      inspector.endTimeSelect.disabled = !editable;
    }
    if (Array.isArray(inspector.durationButtons)) {
      inspector.durationButtons.forEach((button) => {
        if (!(button instanceof HTMLButtonElement)) {
          return;
        }
        button.disabled = !editable;
      });
    }
    sync_duration_preview(modalTargetEntries);
    if (inspectorDialogOpen()) {
      syncDurationDraftTargets();
      update_inspector_counts(target, ensure_cell(target));
      window.requestAnimationFrame(() => {
        if (target != activeEntry) {
          return;
        }
        update_inspector_counts(target, ensure_cell(target));
      });
    }
  };
  const pick_inspector_editor_source = (entry) => {
    if (entry) {
      const fromEntry = entry.querySelector("entry-detail");
      if (fromEntry) {
        return fromEntry;
      }
    }
    for (const row of rows) {
      const fallback = row.querySelector("entry-cell entry-detail");
      if (fallback) {
        return fallback;
      }
    }
    return null;
  };
  const mount_inspector_entry_editor = (entry, forceReadonly = false) => {
    if (!inspector.slotEditor) {
      return;
    }
    const cellId =
      entry && typeof entry.dataset?.id == "string" ? entry.dataset.id : "";
    const cell = cellId != "" ? cells.get(cellId) ?? null : null;
    if (cell && !forceReadonly) {
      cell.preview_default_group();
    }
    const source = pick_inspector_editor_source(entry);
    if (!source) {
      inspector.slotEditor.replaceChildren();
      inspector.slotEditor.hidden = true;
      return;
    }
    const interactive = !forceReadonly && is_entry_interactive(entry);
    sanitize_and_bind_inspector_editor(
      source,
      inspector.slotEditor,
      Boolean(interactive),
      () => {
        if (!entry) {
          return;
        }
        update_inspector_counts(entry, ensure_cell(entry));
        if (inspectorDialogOpen()) {
          syncDurationDraftTargets();
        }
      },
    );
    inspector.slotEditor.hidden = false;
  };
  const set_inspector_default_state = () => {
    inspectorState.target = "Select a time slot";
    inspectorState.summary = "no slot selected";
    inspectorState.mode = "Read-only booking";
    inspectorState.pending = "0 changes";
    inspectorState.errors = "0 errors";
    render_slot_errors([]);
    if (inspector.save) {
      inspector.save.hidden = true;
    }
    modalDurationSlots = 1;
    modalTargetEntries = [];
    set_inspector_action_label(false, false, false);
    mount_inspector_entry_editor(null, true);
    sync_duration_controls(null, false);
    sync_inspector_modal();
  };
  const update_inspector_selection = (entry, options = {}) => {
    const refreshEditor = options.refreshEditor !== false;
    if (!entry) {
      set_inspector_default_state();
      return;
    }
    const bookingEditable = is_entry_booking_editable(entry);
    const interactive = is_entry_interactive(entry);
    const supportActionable = is_entry_support_actionable(entry);
    const cell = ensure_cell(entry);
    const date = humanize_date_if_needed(entry.dataset.date ?? "");
    const hour = human_hours?.[entry.dataset.hour] ?? entry.dataset.hour ?? "";
    inspectorState.target = `${date}, ${hour}`;
    inspectorState.summary = slot_summary(entry);
    if (entry.dataset.locked == "true") {
      inspectorState.mode = "Save rejected; refresh before retrying";
    } else if (bookingEditable && supportActionable) {
      inspectorState.mode = "Editable booking; support can be assigned";
    } else if (bookingEditable) {
      inspectorState.mode = "Editable booking";
    } else if (supportActionable) {
      inspectorState.mode = "Read-only booking; support can be assigned";
    } else {
      inspectorState.mode = "Read-only booking";
    }
    if (inspector.open) {
      set_inspector_action_label(bookingEditable, supportActionable, true);
    }
    if (inspector.save) {
      inspector.save.hidden = !interactive;
    }
    if (inspector.slotEditor && refreshEditor) {
      mount_inspector_entry_editor(entry);
    }
    sync_duration_controls(entry, bookingEditable);
    update_inspector_counts(entry, cell);
    sync_inspector_modal();
  };

  const update_inspector_empty = (row, col) => {
    if (!row) {
      return;
    }
    const hour = human_hours?.[row.dataset.hour] ?? row.dataset.hour ?? "";
    const day = dayLabelForCol(col);
    inspectorState.target = `${day}, ${hour}`.replace(/^,\s*/, "");
    inspectorState.summary = "open | unassigned | no support requests";
    inspectorState.mode = "Read-only booking";
    update_inspector_counts(null, null);
    mount_inspector_entry_editor(null, true);
    if (inspector.save) {
      inspector.save.hidden = true;
    }
    sync_duration_controls(null, false);
    set_inspector_action_label(false, false, false);
    sync_inspector_modal();
  };
  set_inspector_default_state();
  sync_row_visibility();
  if (inspector.endTimeSelect) {
    inspector.endTimeSelect.addEventListener("change", () => {
      const parsed = Number.parseInt(inspector.endTimeSelect.value, 10);
      if (Number.isNaN(parsed)) {
        return;
      }
      modalDurationSlots = Math.max(1, parsed);
      sync_duration_controls(activeEntry, is_entry_editable(activeEntry));
    });
  }
  if (Array.isArray(inspector.durationButtons)) {
    inspector.durationButtons.forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) {
        return;
      }
      button.addEventListener("click", () => {
        const slots = Number.parseInt(button.dataset.durationSlots ?? "", 10);
        if (Number.isNaN(slots) || slots <= 0) {
          return;
        }
        modalDurationSlots += Math.max(1, slots);
        sync_duration_controls(activeEntry, is_entry_editable(activeEntry));
      });
    });
  }

  const update_load_status = () => {
    if (!loadStatus) {
      return;
    }
    if (templateEditor) {
      loadStatus.hidden = true;
      if (!loadErrorMessage) {
        return;
      }
    }
    if (loadErrorMessage) {
      loadStatus.innerText = `error loading schedule rows: ${loadErrorMessage}`;
      loadStatus.dataset.state = "error";
      loadStatus.hidden = false;
      return;
    }
    if (is_lateral_movement_active()) {
      loadStatus.dataset.state = "ready";
      loadStatus.innerText = "scanning: waiting for pause";
      return;
    }
    if (is_hydration_locked()) {
      loadStatus.dataset.state = "ready";
      loadStatus.innerText = "fast scanning: hydration paused";
      return;
    }
    loadStatus.dataset.state = "ready";
    const total = rows.length;
    const hydrated = rows.filter(
      (row) => row.dataset.hydrated == "true",
    ).length;
    if (total == 0) {
      loadStatus.hidden = true;
      return;
    }
    if (hydrated < total) {
      loadStatus.innerText = `progressive loading: ${hydrated} of ${total} rows ready`;
    } else {
      loadStatus.innerText = `all ${total} rows ready`;
    }
  };

  const HISTORY_REPLACE_THROTTLE_MS = 400;
  const SETTLED_HYDRATE_DEBOUNCE_MS = 300;
  const FAST_SCAN_FETCH_WINDOW_MS = 1500;
  const FAST_SCAN_FETCH_THRESHOLD = 8;
  const FAST_SCAN_LOCK_MS = 2000;
  const PREFETCH_WINDOW_DAYS = 7;
  const PREFETCH_INITIAL_DELAY_MS = 0;
  const PREFETCH_TRIGGER_DELAY_MS = 1500;
  const PREFETCH_COOLDOWN_MS = 4000;
  const PREFETCH_EDGE_TRIGGER_DAYS = 2;
  const SLOT_CACHE_TTL_MS = 4 * 60 * 1000;
  const SLOT_CACHE_MAX_ENTRIES = 3600;

  let windowShiftInFlight = null;
  let scheduleWindowVersion = 0;
  let hydrateAbort = new AbortController();
  let settledHydrateTimer = 0;
  let prefetchTimer = 0;
  let prefetchAbort = null;
  let pendingHistoryTimer = 0;
  let pendingHistoryWrite = null;
  let lastHistoryWriteAt = 0;
  let recentFetchTimestamps = [];
  let movementIdleUntil = 0;
  let hydrationLockUntil = 0;
  let hydrationLockTimer = 0;
  let lastPrefetchRunAt = 0;
  let initialPrefetchScheduled = false;
  let hasCompletedInitialHydration = false;
  let prefetchCoverageStart = null;
  let prefetchCoverageEnd = null;
  const prefetchInFlightRanges = new Set();
  const prefetchRecentRanges = new Map();
  const slotPayloadCache = new Map();

  const cache_key = (dateKey, hour) => `${dateKey}|${hour}`;
  const prune_slot_cache = () => {
    const now = Date.now();
    for (const [key, entry] of slotPayloadCache.entries()) {
      if (!entry || entry.expiresAt <= now) {
        slotPayloadCache.delete(key);
      }
    }
    while (slotPayloadCache.size > SLOT_CACHE_MAX_ENTRIES) {
      const oldest = slotPayloadCache.keys().next().value;
      if (oldest == null) {
        break;
      }
      slotPayloadCache.delete(oldest);
    }
  };
  const read_slot_cache = (dateKey, hour) => {
    prune_slot_cache();
    const key = cache_key(dateKey, hour);
    const entry = slotPayloadCache.get(key);
    if (!entry) {
      return null;
    }
    slotPayloadCache.delete(key);
    slotPayloadCache.set(key, {
      markup: entry.markup,
      expiresAt: Date.now() + SLOT_CACHE_TTL_MS,
    });
    return entry.markup;
  };
  const write_slot_cache = (dateKey, hour, markup) => {
    const key = cache_key(dateKey, hour);
    slotPayloadCache.delete(key);
    slotPayloadCache.set(key, {
      markup: typeof markup == "string" ? markup : "",
      expiresAt: Date.now() + SLOT_CACHE_TTL_MS,
    });
    prune_slot_cache();
  };
  const movement_idle_remaining_ms = () =>
    Math.max(0, movementIdleUntil - Date.now());
  const is_lateral_movement_active = () => movement_idle_remaining_ms() > 0;
  const arm_movement_idle_gate = () => {
    movementIdleUntil = Date.now() + SETTLED_HYDRATE_DEBOUNCE_MS;
  };
  const hydration_lock_remaining_ms = () =>
    Math.max(0, hydrationLockUntil - Date.now());
  const is_hydration_locked = () => hydration_lock_remaining_ms() > 0;
  const queue_lock_release_refresh = () => {
    if (hydrationLockTimer != 0) {
      window.clearTimeout(hydrationLockTimer);
    }
    const delay = Math.max(0, hydration_lock_remaining_ms() + 20);
    hydrationLockTimer = window.setTimeout(() => {
      hydrationLockTimer = 0;
      update_load_status();
      queue_settled_window_hydration(
        scheduleWindowVersion,
        hydrateAbort?.signal ?? null,
      );
    }, delay);
  };
  const activate_hydration_lock = (durationMs = FAST_SCAN_LOCK_MS) => {
    const until = Date.now() + Math.max(0, durationMs);
    if (until <= hydrationLockUntil) {
      return;
    }
    hydrationLockUntil = until;
    recentFetchTimestamps = [];
    if (prefetchAbort) {
      prefetchAbort.abort();
      prefetchAbort = null;
    }
    if (prefetchTimer != 0) {
      window.clearTimeout(prefetchTimer);
      prefetchTimer = 0;
    }
    queue_lock_release_refresh();
    update_load_status();
  };
  const clear_hydration_lock = () => {
    hydrationLockUntil = 0;
    recentFetchTimestamps = [];
    if (hydrationLockTimer != 0) {
      window.clearTimeout(hydrationLockTimer);
      hydrationLockTimer = 0;
    }
  };
  const note_schedule_db_fetch_hit = () => {
    const now = Date.now();
    recentFetchTimestamps.push(now);
    const cutoff = now - FAST_SCAN_FETCH_WINDOW_MS;
    recentFetchTimestamps = recentFetchTimestamps.filter((ts) => ts >= cutoff);
    if (recentFetchTimestamps.length >= FAST_SCAN_FETCH_THRESHOLD) {
      activate_hydration_lock();
    }
  };
  const write_history_state = ({ startYmd, days }) => {
    const params = new URLSearchParams(window.location.search);
    params.set("start", startYmd);
    params.set("days", String(days));
    window.history.replaceState(
      {
        ...(window.history.state || {}),
        scheduleStart: startYmd,
        scheduleDays: days,
      },
      "",
      `${window.location.pathname}?${params.toString()}`,
    );
    lastHistoryWriteAt = Date.now();
  };
  const flush_history_write = () => {
    if (!pendingHistoryWrite) {
      return;
    }
    const payload = pendingHistoryWrite;
    pendingHistoryWrite = null;
    write_history_state(payload);
  };
  const queue_history_write = (payload, { force = false } = {}) => {
    pendingHistoryWrite = payload;
    if (force) {
      if (pendingHistoryTimer != 0) {
        window.clearTimeout(pendingHistoryTimer);
        pendingHistoryTimer = 0;
      }
      flush_history_write();
      return;
    }
    const elapsed = Date.now() - lastHistoryWriteAt;
    if (elapsed >= HISTORY_REPLACE_THROTTLE_MS && pendingHistoryTimer == 0) {
      flush_history_write();
      return;
    }
    const delay = Math.max(0, HISTORY_REPLACE_THROTTLE_MS - elapsed);
    if (pendingHistoryTimer != 0) {
      return;
    }
    pendingHistoryTimer = window.setTimeout(() => {
      pendingHistoryTimer = 0;
      flush_history_write();
    }, delay);
  };

  const clear_settled_window_hydration = () => {
    if (settledHydrateTimer == 0) {
      return;
    }
    window.clearTimeout(settledHydrateTimer);
    settledHydrateTimer = 0;
  };
  const clear_prefetch = () => {
    if (prefetchTimer != 0) {
      window.clearTimeout(prefetchTimer);
      prefetchTimer = 0;
    }
    if (prefetchAbort) {
      prefetchAbort.abort();
      prefetchAbort = null;
    }
  };
  const queue_settled_window_hydration = (
    version = scheduleWindowVersion,
    signal = hydrateAbort?.signal ?? null,
  ) => {
    clear_settled_window_hydration();
    const lockDelay = is_hydration_locked() ? hydration_lock_remaining_ms() : 0;
    const movementDelay = is_lateral_movement_active()
      ? movement_idle_remaining_ms()
      : 0;
    const settleDelay = Math.max(
      SETTLED_HYDRATE_DEBOUNCE_MS,
      lockDelay > 0 ? lockDelay + 32 : 0,
      movementDelay > 0 ? movementDelay + 16 : 0,
    );
    settledHydrateTimer = window.setTimeout(() => {
      settledHydrateTimer = 0;
      if (version != scheduleWindowVersion || signal?.aborted) {
        return;
      }
      if (is_lateral_movement_active()) {
        queue_settled_window_hydration(version, signal);
        return;
      }
      if (is_hydration_locked()) {
        queue_settled_window_hydration(version, signal);
        return;
      }
      void hydrate_rows(rows, { version, signal }).then(() => {
        if (version != scheduleWindowVersion || signal?.aborted) {
          return;
        }
        queue_prefetch_adjacent_windows(version);
      });
    }, settleDelay);
  };

  const syncJumpPermalink = ({ forceHistory = false } = {}) => {
    if (!(scheduleWindow.start instanceof Date)) {
      return;
    }
    const jumpForm = document.querySelector("nav.jump-form form");
    const jumpStartInput = jumpForm?.querySelector('input[name="start"]');
    const jumpDaysInput = jumpForm?.querySelector('input[name="days"]');
    if (jumpStartInput instanceof HTMLInputElement) {
      jumpStartInput.value = ymd(scheduleWindow.start);
    }
    if (jumpDaysInput instanceof HTMLInputElement) {
      jumpDaysInput.value = String(scheduleWindow.requestedDays);
    }
    queue_history_write(
      {
        startYmd: ymd(scheduleWindow.start),
        days: scheduleWindow.requestedDays,
      },
      { force: forceHistory },
    );
  };

  const expandWindow = async (direction) =>
    navigateWindowByDirection(direction);

  const ensureWindowContainsDate = async (target) => {
    let guard = 0;
    const ensureDirection = (date) => {
      const end = visibleEndDate();
      if (end == null) {
        return 0;
      }
      if (date < startDate()) {
        return -1;
      }
      if (date > end) {
        return 1;
      }
      return 0;
    };

    while (guard < 12) {
      const direction = ensureDirection(target);
      if (direction === 0) {
        return true;
      }
      if (windowShiftInFlight) {
        await windowShiftInFlight;
      }
      if (!scheduleWindow.start) {
        return false;
      }
      windowShiftInFlight = expandWindow(direction);
      const moved = await windowShiftInFlight;
      windowShiftInFlight = null;
      if (!moved) {
        return false;
      }
      guard += 1;
    }
    return ensureDirection(target) === 0;
  };

  const queryNextScheduleDay = async (start, direction) => {
    if (!remoteScheduleRows || start == null) {
      return null;
    }
    const url = new URL(nextDayEndpoint, window.location.href);
    url.searchParams.set("start", ymd(start));
    url.searchParams.set("direction", String(direction));
    try {
      const resp = await fetch(url.toString(), {
        headers: {
          Accept: "application/json",
        },
      });
      if (!resp.ok) {
        return null;
      }
      const data = await resp.json();
      const date = data?.date;
      return date == null ? null : parse_ymd(date);
    } catch (_err) {
      return null;
    }
  };
  const navigateToDateWindow = async (
    targetDate,
    {
      usePlaceholders = true,
      deferHydration = true,
      showPlaceholdersOnCacheMiss = false,
      armIdleOnPlaceholder = usePlaceholders,
      bypassHydrationGuards = false,
      countFetchForLock = hasCompletedInitialHydration,
    } = {},
  ) => {
    if (!(targetDate instanceof Date)) {
      return false;
    }
    if (!remoteScheduleRows) {
      return false;
    }
    clear_header_settle_timer();

    const start = startDate();
    const preservedScrollY = window.scrollY;
    const restore_window_scroll = () => {
      const maxScroll = Math.max(
        0,
        document.documentElement.scrollHeight - window.innerHeight,
      );
      const safeScroll = Math.max(0, Math.min(maxScroll, preservedScrollY));
      window.scrollTo({ top: safeScroll, left: 0, behavior: "auto" });
    };
    const currentSelection = {
      row: Number.isInteger(editor.scheduleGrid?.row())
        ? editor.scheduleGrid.row()
        : 0,
      col: Number.isInteger(editor.scheduleGrid?.col())
        ? editor.scheduleGrid.col()
        : 0,
    };

    const daysInput = document.querySelector(
      'nav.jump-form input[name="days"]',
    );
    const parsedDays = Number.parseInt(daysInput?.value ?? "", 10);
    const safeDays = Number.isNaN(parsedDays)
      ? scheduleWindow.requestedDays
      : parsedDays;
    const shouldUsePlaceholders =
      usePlaceholders ||
      (showPlaceholdersOnCacheMiss &&
        !is_window_payload_cached(targetDate, safeDays));

    scheduleWindow.start = targetDate;
    apply_visible_day_layout({
      requestedDays: safeDays,
    });
    clear_header_preview();
    movementSkeletonActive = false;
    scheduleWindowVersion += 1;
    const targetVersion = scheduleWindowVersion;
    if (bypassHydrationGuards) {
      clear_hydration_lock();
    }
    clear_settled_window_hydration();
    clear_prefetch();
    if (hydrateAbort) {
      hydrateAbort.abort();
    }
    hydrateAbort = new AbortController();
    loadErrorMessage = "";

    syncHeaderDates();
    syncJumpPermalink();
    for (const row of rows) {
      row.dataset.loaded = "false";
      row.dataset.hydrated = "false";
      row.dataset.loading = "false";
    }
    if (shouldUsePlaceholders) {
      if (armIdleOnPlaceholder) {
        arm_movement_idle_gate();
      } else {
        movementIdleUntil = 0;
      }
      reset_window_placeholders();
    } else {
      movementIdleUntil = 0;
    }
    sync_row_visibility();
    update_load_status();
    updateEdgeScrollButtons();
    restore_window_scroll();

    const grid = editor.scheduleGrid;
    if (grid) {
      const clampedCol = Math.min(
        Math.max(0, currentSelection.col),
        Math.max(0, scheduleWindow.totalDays - 1),
      );
      grid.focus(currentSelection.row, clampedCol, { scroll: false });
    }

    const hydrationSignal = hydrateAbort.signal;
    if (deferHydration) {
      queue_settled_window_hydration(targetVersion, hydrationSignal);
    } else {
      void hydrate_rows(rows, {
        version: targetVersion,
        signal: hydrationSignal,
        countForLock: countFetchForLock,
        bypassHydrationGuards,
      }).then(() => {
        if (targetVersion != scheduleWindowVersion || hydrationSignal.aborted) {
          return;
        }
        queue_prefetch_adjacent_windows(targetVersion);
      });
    }
    if (start != null) {
      const postGrid = editor.scheduleGrid;
      if (postGrid) {
        const clampedCol = Math.min(
          Math.max(0, currentSelection.col),
          Math.max(0, scheduleWindow.totalDays - 1),
        );
        postGrid.focus(currentSelection.row, clampedCol, { scroll: false });
      }
      restore_window_scroll();
      window.requestAnimationFrame(restore_window_scroll);
    }
    updateEdgeScrollButtons();
    return true;
  };
  const navigateWindowByDirection = async (direction, options = {}) => {
    const start = startDate();
    if (!remoteScheduleRows || start == null) {
      return false;
    }
    return navigateToDateWindow(add_days(start, direction), options);
  };
  const refresh_window_after_layout_change = () => {
    if (!remoteScheduleRows || !(scheduleWindow.start instanceof Date)) {
      syncHeaderDates();
      sync_row_visibility();
      update_load_status();
      return;
    }
    scheduleWindowVersion += 1;
    const targetVersion = scheduleWindowVersion;
    clear_settled_window_hydration();
    clear_prefetch();
    if (hydrateAbort) {
      hydrateAbort.abort();
    }
    hydrateAbort = new AbortController();
    loadErrorMessage = "";
    for (const row of rows) {
      row.dataset.loaded = "false";
      row.dataset.hydrated = "false";
      row.dataset.loading = "false";
    }
    reset_window_placeholders();
    sync_row_visibility();
    update_load_status();
    queue_settled_window_hydration(targetVersion, hydrateAbort.signal);
  };
  const activate_movement_skeleton = () => {
    if (!remoteScheduleRows || movementSkeletonActive) {
      return;
    }
    movementSkeletonActive = true;
    scheduleWindowVersion += 1;
    const targetVersion = scheduleWindowVersion;
    clear_settled_window_hydration();
    clear_prefetch();
    if (hydrateAbort) {
      hydrateAbort.abort();
    }
    hydrateAbort = new AbortController();
    loadErrorMessage = "";
    for (const row of rows) {
      row.dataset.loaded = "false";
      row.dataset.hydrated = "false";
      row.dataset.loading = "false";
    }
    reset_window_placeholders();
    sync_row_visibility();
    update_load_status();
    queue_settled_window_hydration(targetVersion, hydrateAbort.signal);
  };
  const has_crossed_movement_skeleton_threshold = () =>
    Math.abs(headerPreviewOffsetPx) >= visible_day_column_width_px() * 0.5;
  const settle_header_movement = async () => {
    if (!remoteScheduleRows || headerSettleInFlight) {
      return;
    }
    const start = startDate();
    if (!(start instanceof Date)) {
      clear_header_preview();
      return;
    }
    const colWidth = Math.max(1, visible_day_column_width_px());
    const dayShift = Math.round(headerPreviewOffsetPx / colWidth);
    clear_header_preview();
    update_load_status();
    if (dayShift == 0) {
      movementSkeletonActive = false;
      movementIdleUntil = 0;
      const version = scheduleWindowVersion;
      const signal = hydrateAbort?.signal ?? null;
      void hydrate_rows(rows, { version, signal }).then(() => {
        if (version != scheduleWindowVersion || signal?.aborted) {
          return;
        }
        queue_prefetch_adjacent_windows(version);
      });
      return;
    }
    if (windowShiftInFlight) {
      await windowShiftInFlight;
    }
    headerSettleInFlight = true;
    try {
      windowShiftInFlight = navigateToDateWindow(add_days(start, dayShift), {
        usePlaceholders: false,
        deferHydration: false,
      });
      await windowShiftInFlight;
    } finally {
      windowShiftInFlight = null;
      headerSettleInFlight = false;
      movementSkeletonActive = false;
      clear_header_preview();
      update_load_status();
    }
  };
  const queue_header_settle = () => {
    clear_header_settle_timer();
    headerSettleTimer = window.setTimeout(() => {
      headerSettleTimer = 0;
      void settle_header_movement();
    }, SETTLED_HYDRATE_DEBOUNCE_MS);
  };
  const scrollOneDay = (direction, behavior = "smooth") => {
    const amount = oneDayScrollAmount();
    scrollContainer.scrollBy({
      left: direction * amount,
      behavior,
    });
  };
  const build_range_date_keys = (rangeStart, days) => {
    const keys = [];
    for (let i = 0; i < days; i += 1) {
      keys.push(ymd(add_days(rangeStart, i)));
    }
    return keys;
  };
  const read_cached_window_payload = (chunk, dateKeys) => {
    const payloadByHour = new Map();
    for (const hour of chunk) {
      const cells = [];
      for (const dateKey of dateKeys) {
        const markup = read_slot_cache(dateKey, hour);
        if (markup == null) {
          return null;
        }
        cells.push(markup);
      }
      payloadByHour.set(hour, cells);
    }
    return payloadByHour;
  };
  const is_window_payload_cached = (rangeStart, days) => {
    if (!(rangeStart instanceof Date) || !remoteScheduleRows || days < 1) {
      return false;
    }
    const allHours = rows
      .map((row) => row.dataset.hour)
      .filter((hour) => typeof hour == "string");
    if (allHours.length == 0) {
      return false;
    }
    const dateKeys = build_range_date_keys(rangeStart, days);
    for (let i = 0; i < allHours.length; i += 12) {
      const chunk = allHours.slice(i, i + 12);
      if (read_cached_window_payload(chunk, dateKeys) == null) {
        return false;
      }
    }
    return true;
  };
  const cache_window_payload = (chunk, dateKeys, payloadByHour) => {
    for (const hour of chunk) {
      const payloadCells = Array.isArray(payloadByHour.get(hour))
        ? payloadByHour.get(hour)
        : [];
      for (let i = 0; i < dateKeys.length; i += 1) {
        const markup =
          typeof payloadCells[i] == "string" ? payloadCells[i] : "";
        write_slot_cache(dateKeys[i], hour, markup);
      }
    }
  };
  const apply_window_payload_to_rows = (chunk, windowRange, payloadByHour) => {
    for (const hour of chunk) {
      const row = rowsByHour.get(hour);
      if (!row) {
        continue;
      }
      const slots = [...row.querySelectorAll("td")];
      const payloadCells = Array.isArray(payloadByHour.get(hour))
        ? payloadByHour.get(hour)
        : [];
      for (
        let i = 0;
        i < windowRange.days && i + windowRange.offset < slots.length;
        i += 1
      ) {
        const markup =
          typeof payloadCells[i] == "string" ? payloadCells[i] : "";
        const targetCell = slots[i + windowRange.offset];
        const parsedMarkup = parse_schedule_cell_markup(markup);
        if (!targetCell) {
          continue;
        }
        if (parsedMarkup.length == 0) {
          targetCell.dataset.placeholder = "true";
          delete targetCell.dataset.empty;
          targetCell.replaceChildren(
            build_slot_placeholder({ shadow: row_is_in_viewport(row) }),
          );
          continue;
        }
        delete targetCell.dataset.placeholder;
        targetCell.replaceChildren(...parsedMarkup);
        const renderedEntry = targetCell.querySelector("entry-cell");
        if (renderedEntry instanceof HTMLElement) {
          sync_slot_empty_state(renderedEntry);
        } else {
          delete targetCell.dataset.empty;
        }
      }
      row.dataset.loading = "false";
      row.querySelectorAll("entry-cell").forEach((entry) => {
        if (!("active" in entry.dataset)) {
          entry.dataset.active = "false";
        }
      });
    }
  };
  const fetch_window_payload = async (
    rangeStart,
    days,
    chunk,
    signal,
    { countForLock = true } = {},
  ) => {
    const url = new URL(scheduleWindow.endpoint, window.location.href);
    url.searchParams.set("start", ymd(rangeStart));
    url.searchParams.set("days", String(days));
    url.searchParams.set("hours", chunk.join(","));

    if (countForLock) {
      note_schedule_db_fetch_hit();
    }
    const resp = await fetch(url.toString(), {
      signal,
      headers: {
        Accept: "application/json",
      },
    });
    if (!resp.ok) {
      throw new Error(`api returned ${resp.status}`);
    }

    const data = await resp.json();
    const payloadRows = Array.isArray(data.rows) ? data.rows : [];
    const payloadByHour = new Map();
    for (const row of payloadRows) {
      payloadByHour.set(
        String(row.hour),
        Array.isArray(row.cells) ? row.cells : [],
      );
    }
    return payloadByHour;
  };
  const clone_utc_date = (date) => {
    if (!(date instanceof Date)) {
      return null;
    }
    return new Date(date.getTime());
  };
  const normalize_prefetch_coverage = () => {
    if (
      !(prefetchCoverageStart instanceof Date) ||
      !(prefetchCoverageEnd instanceof Date)
    ) {
      prefetchCoverageStart = null;
      prefetchCoverageEnd = null;
      return;
    }
    const currentStart = startDate();
    const currentEnd = visibleEndDate();
    if (!(currentStart instanceof Date) || !(currentEnd instanceof Date)) {
      return;
    }
    if (
      currentEnd < prefetchCoverageStart ||
      currentStart > prefetchCoverageEnd
    ) {
      prefetchCoverageStart = null;
      prefetchCoverageEnd = null;
    }
  };
  const merge_prefetch_coverage = (rangeStart, days) => {
    if (!(rangeStart instanceof Date) || days < 1) {
      return;
    }
    const rangeEnd = add_days(rangeStart, days - 1);
    if (
      !(prefetchCoverageStart instanceof Date) ||
      rangeStart < prefetchCoverageStart
    ) {
      prefetchCoverageStart = clone_utc_date(rangeStart);
    }
    if (
      !(prefetchCoverageEnd instanceof Date) ||
      rangeEnd > prefetchCoverageEnd
    ) {
      prefetchCoverageEnd = clone_utc_date(rangeEnd);
    }
  };
  const prefetch_range_key = (rangeStart, days) => `${ymd(rangeStart)}|${days}`;
  const prune_recent_prefetch_ranges = () => {
    const cutoff = Date.now() - PREFETCH_COOLDOWN_MS * 3;
    for (const [key, completedAt] of prefetchRecentRanges.entries()) {
      if (completedAt < cutoff) {
        prefetchRecentRanges.delete(key);
      }
    }
  };
  const build_prefetch_plan = () => {
    const currentStart = startDate();
    const currentEnd = visibleEndDate();
    if (!(currentStart instanceof Date) || !(currentEnd instanceof Date)) {
      return [];
    }
    normalize_prefetch_coverage();
    if (
      !(prefetchCoverageStart instanceof Date) ||
      !(prefetchCoverageEnd instanceof Date)
    ) {
      return [
        {
          start: add_days(currentStart, -PREFETCH_WINDOW_DAYS),
          days: PREFETCH_WINDOW_DAYS,
        },
        { start: add_days(currentEnd, 1), days: PREFETCH_WINDOW_DAYS },
      ];
    }
    const plan = [];
    const daysToLeftEdge = days_since(prefetchCoverageStart, currentStart);
    if (daysToLeftEdge <= PREFETCH_EDGE_TRIGGER_DAYS) {
      plan.push({
        start: add_days(prefetchCoverageStart, -PREFETCH_WINDOW_DAYS),
        days: PREFETCH_WINDOW_DAYS,
      });
    }
    const daysToRightEdge = days_since(currentEnd, prefetchCoverageEnd);
    if (daysToRightEdge <= PREFETCH_EDGE_TRIGGER_DAYS) {
      plan.push({
        start: add_days(prefetchCoverageEnd, 1),
        days: PREFETCH_WINDOW_DAYS,
      });
    }
    return plan;
  };
  const fetch_and_cache_range = async (
    rangeStart,
    days,
    {
      version = scheduleWindowVersion,
      signal = null,
      countForLock = true,
    } = {},
  ) => {
    if (!(rangeStart instanceof Date) || !remoteScheduleRows || days < 1) {
      return false;
    }
    const allHours = rows
      .map((row) => row.dataset.hour)
      .filter((hour) => typeof hour == "string");
    if (allHours.length == 0) {
      return false;
    }
    const dateKeys = build_range_date_keys(rangeStart, days);
    for (let i = 0; i < allHours.length; i += 12) {
      if (
        version != scheduleWindowVersion ||
        signal?.aborted ||
        is_hydration_locked() ||
        is_lateral_movement_active()
      ) {
        return false;
      }
      const chunk = allHours.slice(i, i + 12);
      if (read_cached_window_payload(chunk, dateKeys) != null) {
        continue;
      }
      const payloadByHour = await fetch_window_payload(
        rangeStart,
        days,
        chunk,
        signal,
        { countForLock },
      );
      if (version != scheduleWindowVersion || signal?.aborted) {
        return false;
      }
      cache_window_payload(chunk, dateKeys, payloadByHour);
    }
    return true;
  };
  const queue_prefetch_adjacent_windows = (
    version = scheduleWindowVersion,
    { initial = false } = {},
  ) => {
    if (!remoteScheduleRows || !(scheduleWindow.start instanceof Date)) {
      return;
    }
    if (initial && initialPrefetchScheduled) {
      return;
    }
    if (initial) {
      initialPrefetchScheduled = true;
    }
    if (prefetchTimer != 0) {
      window.clearTimeout(prefetchTimer);
      prefetchTimer = 0;
    }
    if (prefetchAbort) {
      prefetchAbort.abort();
      prefetchAbort = null;
    }
    const now = Date.now();
    const sinceLastPrefetch = now - lastPrefetchRunAt;
    const cooldownDelay =
      initial || sinceLastPrefetch >= PREFETCH_COOLDOWN_MS
        ? 0
        : PREFETCH_COOLDOWN_MS - sinceLastPrefetch;
    const triggerDelay = initial
      ? PREFETCH_INITIAL_DELAY_MS
      : PREFETCH_TRIGGER_DELAY_MS;
    const scheduleDelay = Math.max(triggerDelay, cooldownDelay);
    prefetchTimer = window.setTimeout(() => {
      prefetchTimer = 0;
      if (
        version != scheduleWindowVersion ||
        is_hydration_locked() ||
        is_lateral_movement_active() ||
        !(scheduleWindow.start instanceof Date)
      ) {
        return;
      }
      const plan = build_prefetch_plan();
      if (plan.length == 0) {
        return;
      }
      const controller = new AbortController();
      prefetchAbort = controller;
      lastPrefetchRunAt = Date.now();
      void (async () => {
        try {
          prune_recent_prefetch_ranges();
          for (const range of plan) {
            const rangeKey = prefetch_range_key(range.start, range.days);
            const completedAt = prefetchRecentRanges.get(rangeKey) ?? 0;
            if (prefetchInFlightRanges.has(rangeKey)) {
              continue;
            }
            if (Date.now() - completedAt < PREFETCH_COOLDOWN_MS) {
              continue;
            }
            prefetchInFlightRanges.add(rangeKey);
            try {
              const finished = await fetch_and_cache_range(
                range.start,
                range.days,
                {
                  version,
                  signal: controller.signal,
                  countForLock: false,
                },
              );
              if (finished) {
                merge_prefetch_coverage(range.start, range.days);
                prefetchRecentRanges.set(rangeKey, Date.now());
              }
            } finally {
              prefetchInFlightRanges.delete(rangeKey);
            }
          }
        } catch (err) {
          if (!(err && err.name == "AbortError")) {
            console.warn("schedule prefetch failed", err);
          }
        } finally {
          if (prefetchAbort == controller) {
            prefetchAbort = null;
          }
        }
      })();
    }, scheduleDelay);
  };

  const load_rows = async (
    hoursToLoad,
    {
      version = scheduleWindowVersion,
      signal = null,
      countForLock = hasCompletedInitialHydration,
      bypassHydrationGuards = false,
    } = {},
  ) => {
    if (!remoteScheduleRows) {
      return;
    }

    const requested = [];
    for (const h of hoursToLoad) {
      const hour = String(h);
      const row = rowsByHour.get(hour);
      if (
        !row ||
        row.dataset.loaded == "true" ||
        row.dataset.loading == "true"
      ) {
        continue;
      }
      row.dataset.loading = "true";
      requested.push(hour);
    }
    if (requested.length == 0) {
      return;
    }

    const blockedByHydrationGuard = () =>
      !bypassHydrationGuards &&
      (is_hydration_locked() || is_lateral_movement_active());

    if (blockedByHydrationGuard()) {
      for (const hour of requested) {
        const row = rowsByHour.get(hour);
        if (row) {
          row.dataset.loading = "false";
        }
      }
      return;
    }

    const chunks = [];
    for (let i = 0; i < requested.length; i += 12) {
      chunks.push(requested.slice(i, i + 12));
    }

    const dayBatchSize = 31;
    const rangeStarts = [];
    for (
      let offset = 0;
      offset < scheduleWindow.totalDays;
      offset += dayBatchSize
    ) {
      const days = Math.min(dayBatchSize, scheduleWindow.totalDays - offset);
      rangeStarts.push({ offset, days });
    }

    for (const chunk of chunks) {
      if (
        version != scheduleWindowVersion ||
        signal?.aborted ||
        blockedByHydrationGuard()
      ) {
        for (const hour of chunk) {
          const row = rowsByHour.get(hour);
          if (row) {
            row.dataset.loading = "false";
          }
        }
        return;
      }
      try {
        for (const windowRange of rangeStarts) {
          if (
            version != scheduleWindowVersion ||
            signal?.aborted ||
            blockedByHydrationGuard()
          ) {
            break;
          }
          const rangeStart = add_days(scheduleWindow.start, windowRange.offset);
          const dateKeys = build_range_date_keys(rangeStart, windowRange.days);
          let payloadByHour = read_cached_window_payload(chunk, dateKeys);
          if (payloadByHour == null) {
            payloadByHour = await fetch_window_payload(
              rangeStart,
              windowRange.days,
              chunk,
              signal,
              { countForLock },
            );
            if (version != scheduleWindowVersion || signal?.aborted) {
              break;
            }
            cache_window_payload(chunk, dateKeys, payloadByHour);
          }
          if (version != scheduleWindowVersion || signal?.aborted) {
            break;
          }
          apply_window_payload_to_rows(chunk, windowRange, payloadByHour);
        }

        if (
          version != scheduleWindowVersion ||
          signal?.aborted ||
          blockedByHydrationGuard()
        ) {
          for (const hour of chunk) {
            const row = rowsByHour.get(hour);
            if (row) {
              row.dataset.loading = "false";
            }
          }
          return;
        }
        for (const hour of chunk) {
          const row = rowsByHour.get(hour);
          if (!row) {
            continue;
          }
          row.dataset.loaded = "true";
        }
        loadErrorMessage = "";
      } catch (err) {
        for (const hour of chunk) {
          const row = rowsByHour.get(hour);
          if (!row) {
            continue;
          }
          row.dataset.loading = "false";
        }
        if (err && err.name == "AbortError") {
          return;
        }
        loadErrorMessage = err instanceof Error ? err.message : "unknown";
      }
    }
  };

  const ensure_cell = (entry) => {
    if (!entry) {
      return null;
    }
    const id = entry.dataset.id;
    if (!id) {
      return null;
    }
    const preexisting = cells.get(id);
    if (preexisting) {
      return preexisting;
    }

    const cell = new Cell(entry, cfg);
    cells.set(id, cell);
    if (cell.invalid) {
      invalid.add(cell);
    }
    if (cell.changed) {
      changed.add(cell);
      if (cell.invalid) {
        changedInvalid.add(cell);
      }
    }
    update_caption("error", any_invalid());
    update_caption("changed", any_changed());
    update_pending_review_control();
    const activeTargets = inspector_target_entries(activeEntry);
    if (
      activeEntry &&
      (activeEntry.dataset.id == cell.id ||
        activeTargets.some((target) => target.dataset.id == cell.id))
    ) {
      update_inspector_counts(activeEntry, ensure_cell(activeEntry) ?? cell);
    }
    return cell;
  };

  const hydrate_rows = async (
    targets,
    {
      version = scheduleWindowVersion,
      signal = hydrateAbort?.signal ?? null,
      countForLock = hasCompletedInitialHydration,
      bypassHydrationGuards = false,
    } = {},
  ) => {
    const rowsToHydrate = targets.filter(
      (row) => row && row.dataset.hydrated != "true",
    );
    if (rowsToHydrate.length == 0) {
      return;
    }

    const hours = rowsToHydrate
      .map((row) => row.dataset.hour)
      .filter((hour) => typeof hour == "string");
    if (hours.length > 0) {
      await load_rows(hours, {
        version,
        signal,
        countForLock,
        bypassHydrationGuards,
      });
    }

    if (version != scheduleWindowVersion || signal?.aborted) {
      return;
    }

    for (const row of rowsToHydrate) {
      if (row.dataset.loaded != "true") {
        continue;
      }
      row.querySelectorAll("td entry-cell").forEach((entry) => {
        ensure_cell(entry);
      });
      row.dataset.hydrated = "true";
    }
    sync_row_visibility();
    update_load_status();
  };

  const hydrate_row = async (row) => {
    await hydrate_rows([row]);
  };

  const initialRows = templateEditor ? rows : displayed_rows_for_hydration();
  void hydrate_rows(initialRows, { countForLock: false }).finally(() => {
    hasCompletedInitialHydration = true;
    queue_placeholder_shadow_sync();
    if (!templateEditor) {
      queue_prefetch_adjacent_windows(scheduleWindowVersion, { initial: true });
    }
  });
  if (!templateEditor) {
    queue_settled_window_hydration();
  }

  if (templateEditor) {
    // Template schedules are small and fully present in the DOM, so hydrate
    // the full grid immediately via the initial rows path above.
  } else if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        const visible = [];
        for (const observed of entries) {
          if (!observed.isIntersecting) {
            continue;
          }
          visible.push(observed.target);
          io.unobserve(observed.target);
        }
        if (visible.length > 0) {
          void hydrate_rows(visible);
        }
      },
      {
        root: null,
        rootMargin: "160px 0px",
      },
    );
    for (const row of rows) {
      if (row.dataset.hydrated == "true") {
        continue;
      }
      io.observe(row);
    }
  } else {
    void hydrate_rows(rows);
  }

  update_caption("error", any_invalid());
  update_caption("changed", any_changed());
  update_pending_review_control();
  update_load_status();
  update_inspector_counts();

  const editorTable = editor;
  let jumpLookupInFlight = false;
  const canJumpControls = remoteScheduleRows && nextDayEndpoint != "";
  const wireJumpControl = (button, direction) => {
    if (!button) {
      return;
    }
    button.disabled = !canJumpControls;
    if (!canJumpControls) {
      return;
    }
    button.addEventListener("click", (evt) => {
      evt.preventDefault();
      const grid = editor.scheduleGrid;
      const row = grid && Number.isInteger(grid.row()) ? grid.row() : 0;
      const col = grid && Number.isInteger(grid.col()) ? grid.col() : 0;
      emit_jump_fallback(direction, row, col, "control");
    });
  };
  wireJumpControl(jumpPrevDayBtn, -1);
  wireJumpControl(jumpNextDayBtn, 1);

  const wireEdgeScrollControl = (button, direction) => {
    if (!button) {
      return;
    }
    button.addEventListener("click", (evt) => {
      evt.preventDefault();
      void (async () => {
        if (remoteScheduleRows) {
          clear_header_settle_timer();
          clear_header_preview();
          await navigateWindowByDirection(direction, {
            usePlaceholders: false,
            deferHydration: false,
            showPlaceholdersOnCacheMiss: true,
            armIdleOnPlaceholder: false,
            bypassHydrationGuards: true,
            countFetchForLock: false,
          });
          return;
        }
        const atEdge = direction < 0 ? atLeftEdge() : atRightEdge();
        if (hasHorizontalOverflow() && !atEdge) {
          scrollOneDay(direction);
          return;
        }
        scrollOneDay(direction, "auto");
      })();
    });
  };
  wireEdgeScrollControl(scrollPrevDayBtn, -1);
  wireEdgeScrollControl(scrollNextDayBtn, 1);
  updateEdgeScrollButtons();
  let layoutResizeTimer = 0;
  window.addEventListener(
    "resize",
    () => {
      updateEdgeScrollButtons();
      if (!remoteScheduleRows) {
        return;
      }
      if (layoutResizeTimer != 0) {
        window.clearTimeout(layoutResizeTimer);
      }
      layoutResizeTimer = window.setTimeout(() => {
        layoutResizeTimer = 0;
        lockedLeadingColumnWidthPx = 0;
        const layout = apply_visible_day_layout({
          requestedDays: scheduleWindow.requestedDays,
        });
        syncHeaderDates();
        queue_floating_header_sync();
        if (layout.changed && layout.grew) {
          clear_header_preview();
          refresh_window_after_layout_change();
        }
      }, 120);
    },
    { passive: true },
  );

  document.addEventListener(JUMP_TO_WINDOW_EVENT, async (evt) => {
    if (!remoteScheduleRows) {
      return;
    }
    const requestedStart = parse_ymd(String(evt.detail?.start ?? ""));
    if (!(requestedStart instanceof Date)) {
      return;
    }
    evt.preventDefault();
    const jumpFormElm = document.querySelector("nav.jump-form form");
    const jumpStartInput = jumpFormElm?.querySelector('input[name="start"]');
    const jumpDaysInput = jumpFormElm?.querySelector('input[name="days"]');
    const parsedDays = Number.parseInt(String(evt.detail?.days ?? ""), 10);
    const safeDays = Number.isNaN(parsedDays)
      ? scheduleWindow.requestedDays
      : Math.min(31, Math.max(1, parsedDays));
    if (jumpStartInput instanceof HTMLInputElement) {
      jumpStartInput.value = ymd(requestedStart);
    }
    if (jumpDaysInput instanceof HTMLInputElement) {
      jumpDaysInput.value = String(safeDays);
    }
    clear_header_settle_timer();
    clear_header_preview();
    if (windowShiftInFlight) {
      await windowShiftInFlight;
    }
    windowShiftInFlight = navigateToDateWindow(requestedStart);
    const moved = await windowShiftInFlight;
    windowShiftInFlight = null;
    if (moved) {
      return;
    }
    const fallbackUrl = String(evt.detail?.url ?? "");
    if (fallbackUrl != "") {
      window.location.assign(fallbackUrl);
    }
  });

  document.addEventListener(JUMP_TO_NEXT_NON_EMPTY_DAY_EVENT, async (evt) => {
    if (jumpLookupInFlight) {
      return;
    }
    jumpLookupInFlight = true;
    try {
      const source = String(evt.detail?.source ?? "grid");
      const direction = Number(evt.detail?.direction);
      const row = Number.parseInt(evt.detail?.row, 10);
      const col = Number.parseInt(evt.detail?.col, 10);
      if (
        (direction !== -1 && direction !== 1) ||
        Number.isNaN(row) ||
        Number.isNaN(col)
      ) {
        return;
      }
      const current = dateForCol(col);
      if (!remoteScheduleRows || current == null || nextDayEndpoint == "") {
        return;
      }
      const grid = editor.scheduleGrid;
      if (!grid) {
        return;
      }

      if (windowShiftInFlight) {
        await windowShiftInFlight;
      }
      clear_header_settle_timer();
      clear_header_preview();
      const nextDate = await queryNextScheduleDay(current, direction);
      if (nextDate == null) {
        if (source == "control") {
          announce(
            direction < 0
              ? "no earlier non-empty day found"
              : "no later non-empty day found",
          );
          return;
        }
        grid.focus(row, col + direction, { scroll: false });
        return;
      }

      const movedIntoWindow = await ensureWindowContainsDate(nextDate);
      if (!movedIntoWindow) {
        await navigateToDateWindow(nextDate);
        return;
      }

      const windowStart = startDate();
      if (windowStart == null) {
        return;
      }
      const targetCol = days_since(windowStart, nextDate);
      grid.focus(row, targetCol, { scroll: false });
    } finally {
      jumpLookupInFlight = false;
    }
  });

  document.addEventListener(SHIFT_WINDOW_BY_EDGE_ARROW_EVENT, async (evt) => {
    const direction = Number(evt.detail?.direction);
    const row = Number.parseInt(evt.detail?.row, 10);
    if ((direction !== -1 && direction !== 1) || !remoteScheduleRows) {
      return;
    }
    const grid = editor.scheduleGrid;
    if (!grid) {
      return;
    }
    const currentCol = grid.col();
    const atBoundary =
      direction < 0
        ? currentCol <= 0
        : currentCol >= Math.max(0, scheduleWindow.totalDays - 1);
    if (!atBoundary) {
      return;
    }
    clear_header_settle_timer();
    clear_header_preview();
    if (windowShiftInFlight) {
      await windowShiftInFlight;
    }
    windowShiftInFlight = navigateWindowByDirection(direction, {
      usePlaceholders: false,
      deferHydration: false,
      showPlaceholdersOnCacheMiss: true,
      armIdleOnPlaceholder: false,
      bypassHydrationGuards: true,
      countFetchForLock: false,
    });
    const moved = await windowShiftInFlight;
    windowShiftInFlight = null;
    if (!moved) {
      return;
    }
    const targetCol =
      direction < 0 ? 0 : Math.max(0, scheduleWindow.totalDays - 1);
    const targetRow = Number.isNaN(row) ? grid.row() : row;
    grid.focus(targetRow, targetCol, { scroll: false });
  });

  if (editorTable) {
    editorTable.addEventListener("grid_selection", (evt) => {
      const currentSelectionVersion = ++selectionVersion;
      const row = parseInt(evt.detail?.row, 10);
      const col = parseInt(evt.detail?.col, 10);
      const entry = evt.detail?.entry;
      const rowElm = rows[row];
      if (!entry && rowElm == null) {
        return;
      }
      if (entry) {
        void hydrate_row(entry.closest("tr"));
        ensure_cell(entry);
        activeEntry = entry;
        update_inspector_selection(entry);
        return;
      }

      void hydrate_row(rowElm).then(() => {
        if (currentSelectionVersion !== selectionVersion) {
          return;
        }
        const tds = rowElm.querySelectorAll("td");
        const td = tds[col];
        if (!td) {
          update_inspector_empty(rowElm, col);
          return;
        }
        const hydrated = td.querySelector("entry-cell");
        if (!hydrated) {
          activeEntry = null;
          update_inspector_empty(rowElm, col);
          return;
        }
        ensure_cell(hydrated);
        hydrated.dataset.active = "true";
        activeEntry = hydrated;
        update_inspector_selection(hydrated);
      });
    });
  }

  let scrollExpandTick = null;
  const expandOnScroll = () => {
    return;
  };
  scrollContainer.addEventListener("scroll", () => {
    if (scrollExpandTick != null) {
      return;
    }
    scrollExpandTick = window.requestAnimationFrame(() => {
      scrollExpandTick = null;
      updateEdgeScrollButtons();
      expandOnScroll();
    });
  });
  const wheelSurface =
    scrollShell instanceof HTMLElement ? scrollShell : scrollContainer;
  const wheel_delta_to_px = (evt, delta) => {
    if (!Number.isFinite(delta)) {
      return 0;
    }
    switch (evt.deltaMode) {
      case 1:
        return delta * 16;
      case 2:
        return delta * window.innerHeight;
      default:
        return delta;
    }
  };
  wheelSurface.addEventListener(
    "wheel",
    (evt) => {
      const absX = Math.abs(evt.deltaX);
      const absY = Math.abs(evt.deltaY);
      const horizontalIntent = absX > absY || (evt.shiftKey && absY > 0);
      if (!horizontalIntent) {
        return;
      }
      const delta =
        absX >= absY ? evt.deltaX : evt.shiftKey ? evt.deltaY : evt.deltaX;
      if (!Number.isFinite(delta) || delta == 0) {
        return;
      }
      const deltaPx = wheel_delta_to_px(evt, delta);
      if (!Number.isFinite(deltaPx) || deltaPx == 0) {
        return;
      }
      // Consume horizontal-intent wheel gestures only while interacting with
      // the schedule grid surface to prevent browser back/forward swipe there.
      evt.preventDefault();
      if (!remoteScheduleRows) {
        scrollContainer.scrollBy({ left: deltaPx, behavior: "auto" });
        return;
      }
      if (headerSettleInFlight) {
        return;
      }
      headerPreviewOffsetPx += deltaPx * 0.5;
      if (has_crossed_movement_skeleton_threshold()) {
        activate_movement_skeleton();
      }
      arm_movement_idle_gate();
      apply_header_preview();
      update_load_status();
      queue_settled_window_hydration(
        scheduleWindowVersion,
        hydrateAbort?.signal ?? null,
      );
      queue_header_settle();
    },
    { passive: false, capture: true },
  );

  const expando = document.querySelector("#expando");
  if (expando) {
    expando.addEventListener("click", () => {
      const newlyVisible = rows
        .filter((row) => row.dataset.hydrated != "true")
        .slice(0, 2);
      if (newlyVisible.length > 0) {
        void hydrate_rows(newlyVisible);
      }
    });
  }

  const preselected = scrollContainer.querySelector(
    "entry-cell[data-active=true]",
  );
  if (preselected) {
    void hydrate_row(preselected.closest("tr"));
    ensure_cell(preselected);
    activeEntry = preselected;
    update_inspector_selection(preselected);
  }
  sync_row_visibility();

  container.addEventListener("cell_change", (evt) => {
    const cell = evt.detail;
    if (
      "serverErrors" in cell.elm.dataset &&
      cell.preserveServerErrors !== true
    ) {
      delete cell.elm.dataset.serverErrors;
    }
    const serverErrorRecord = serverErrorState.get(String(cell.id));
    const shouldPreserveServerErrors =
      cell.preserveServerErrors === true ||
      (serverErrorRecord != null &&
        sameCellValues(serverErrorRecord.snapshot, snapshotCellValues(cell)));
    if (!shouldPreserveServerErrors) {
      serverErrorState.delete(String(cell.id));
    } else if (serverErrorRecord != null) {
      cell.elm.dataset.serverErrors = JSON.stringify(serverErrorRecord.errors);
      cell.elm.dataset.error = "true";
    }

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
    update_pending_review_control();

    // add the beforeunload handler if there are changes
    // and remove it if not
    setBeforeUnload(any_changed());
    sync_row_visibility();
    update_inspector_counts();
    if (activeEntry != null && activeEntry.dataset.id == cell.id) {
      update_inspector_selection(activeEntry, { refreshEditor: false });
    }
  });

  const commitCellState = (cell) => {
    if (!cell) {
      return;
    }
    if (cell.institute) {
      cell.orig.institute = cell.institute.value;
    }
    cell.orig.group = cell.group.value;
    cell.orig.member = cell.member.value;
    for (const sr of Object.values(cell.sr)) {
      if (!sr.requested) {
        continue;
      }
      const requested = sr.requested.checked;
      sr.orig.requested = requested;
      sr.orig.handler = requested ? sr.handler?.value ?? "" : "";
      if (sr.subkind) {
        const current = sr.subkind.value;
        sr.orig.subkind = current;
      }
    }
    cell.update();
    if ("serverErrors" in cell.elm.dataset) {
      delete cell.elm.dataset.serverErrors;
    }
    serverErrorState.delete(String(cell.id));
    changed.delete(cell);
    invalid.delete(cell);
    changedInvalid.delete(cell);
    update_pending_review_control();
  };
  const remapCellIdentity = (oldId, newId) => {
    const oldKey = String(oldId ?? "");
    const newKey = String(newId ?? "");
    if (!oldKey || !newKey || oldKey == newKey) {
      return;
    }
    const cell = cells.get(oldKey);
    if (!cell) {
      return;
    }
    cells.delete(oldKey);
    cell.id = newKey;
    cell.elm.dataset.id = newKey;
    cells.set(newKey, cell);
    if (serverErrorState.has(oldKey)) {
      serverErrorState.set(newKey, serverErrorState.get(oldKey));
      serverErrorState.delete(oldKey);
    }
    if (activeEntry && activeEntry.dataset.id == oldKey) {
      activeEntry.dataset.id = newKey;
    }
  };
  const readCellValues = (cell) => {
    const out = {
      institute: cell.institute?.value ?? "",
      group: cell.group?.value ?? "",
      member: cell.member?.value ?? "",
      sr: {},
    };
    for (const [kind, sr] of Object.entries(cell.sr)) {
      out.sr[kind] = {
        requested: Boolean(sr.requested?.checked),
        handler: sr.handler?.value ?? "",
        subkind: sr.subkind ? sr.subkind.value : "",
      };
    }
    return out;
  };
  const buildDiffForValues = (cell, values) => {
    if (!cell || !values) {
      return null;
    }
    const diff = {
      id: cell.id,
      date: cell.date,
      hour: cell.hour,
    };
    if (cell.institute && values.institute != cell.orig.institute) {
      diff.institute = [cell.orig.institute, values.institute];
    }
    if (values.group != cell.orig.group) {
      diff.group = [cell.orig.group, values.group];
    }
    if (values.member != cell.orig.member) {
      diff.member = [cell.orig.member, values.member];
    }
    for (const [kind, sr] of Object.entries(cell.sr)) {
      const incoming = values.sr?.[kind] ?? {
        requested: Boolean(sr.requested?.checked),
        handler: sr.requested?.checked ? sr.handler?.value ?? "" : "",
        subkind: sr.subkind ? sr.subkind.value : "",
      };
      const incomingRequested = Boolean(incoming.requested);
      const incomingHandler = incomingRequested ? incoming.handler ?? "" : "";
      const requestedChanged =
        sr.requested && incomingRequested != sr.orig.requested;
      const handlerChanged = sr.handler && incomingHandler != sr.orig.handler;
      const subkindChanged =
        sr.subkind &&
        incomingRequested &&
        (sr.isNew || incoming.subkind != sr.orig.subkind);
      if (!(requestedChanged || handlerChanged || subkindChanged)) {
        continue;
      }
      const srDiff = {};
      if (requestedChanged) {
        srDiff.requested = incomingRequested;
      }
      if (handlerChanged) {
        srDiff.handler = [sr.orig.handler, incomingHandler];
      }
      if (sr.subkind) {
        if (sr.isNew) {
          srDiff.subkind = ["", incoming.subkind];
        } else if (incoming.subkind != sr.orig.subkind) {
          srDiff.subkind = [sr.orig.subkind, incoming.subkind];
        }
        srDiff.effectiveSubkind = incoming.subkind;
      }
      diff[kind] = srDiff;
    }
    return Object.keys(diff).length > 3 ? diff : null;
  };
  const buildDiffBatchFromCells = (targetCells) => {
    const targetList = Array.isArray(targetCells)
      ? targetCells.filter(Boolean)
      : [];
    const diffs = targetList.map((cell) => cell.diff()).filter(Boolean);
    diffs.sort(compareCellsChronologically);
    return { targetCells: targetList, diffs };
  };
  const setCellSaveErrors = (cell, slotErrors = []) => {
    if (!cell) {
      return;
    }
    serverErrorState.set(String(cell.id), {
      errors: slotErrors,
      snapshot: snapshotCellValues(cell),
    });
    cell.elm.dataset.serverErrors = JSON.stringify(slotErrors);
    cell.elm.dataset.error = "true";
    invalid.add(cell);
    changedInvalid.add(cell);
  };
  const planOverwriteRebase = (cell, rawError) => {
    if (!cell || !rawError || rawError.type != "overwrote") {
      return null;
    }
    const key = String(rawError.key ?? "")
      .trim()
      .toLowerCase();
    const expected = rawError.expected == null ? "" : String(rawError.expected);
    if (key == "institute" && cell.institute) {
      return () => {
        cell.orig.institute = expected;
      };
    }
    if (key == "group") {
      return () => {
        cell.orig.group = expected;
      };
    }
    if (key == "member") {
      return () => {
        cell.orig.member = expected;
      };
    }
    const srKind = {
      "medical handler": "med",
      "training handler": "train",
      "technologist handler": "tech",
    }[key];
    if (srKind && cell.sr?.[srKind]) {
      return () => {
        cell.sr[srKind].orig.handler = expected;
      };
    }
    return null;
  };
  const rebaseCellFromOverwriteErrors = (cell, slotErrors = []) => {
    if (!cell || !Array.isArray(slotErrors) || slotErrors.length == 0) {
      return false;
    }
    const rebases = [];
    for (const rawError of slotErrors) {
      const rebase = planOverwriteRebase(cell, rawError);
      if (rebase == null) {
        return false;
      }
      rebases.push(rebase);
    }
    delete cell.elm.dataset.serverErrors;
    serverErrorState.delete(String(cell.id));
    for (const rebase of rebases) {
      rebase();
    }
    cell.update();
    return true;
  };
  const applySaveErrors = (data) => {
    const failedIds = data.errors ? Object.keys(data.errors) : [];
    if (failedIds.length == 0) {
      return;
    }
    for (const id of failedIds) {
      const errCell = cells.get(String(id));
      if (!errCell) {
        continue;
      }
      const slotErrors = Array.isArray(data.errors?.[id])
        ? data.errors[id]
        : [];
      if (rebaseCellFromOverwriteErrors(errCell, slotErrors)) {
        continue;
      }
      setCellSaveErrors(errCell, slotErrors);
    }
    update_caption("error", any_invalid());
    update_caption("changed", any_changed());
    update_pending_review_control();
    setBeforeUnload(any_changed());
    if (activeEntry) {
      update_inspector_selection(activeEntry);
    }
  };
  const submitDiffBatch = (
    diffs,
    targetCells,
    {
      notify = true,
      closeInspectorOnSuccess = false,
      applyValues = (cell) => readCellValues(cell),
    } = {},
  ) => {
    result_dialog(
      async (signal) => {
        const csrf_token = document.querySelector("#csrf_token").value;
        const body = JSON.stringify({
          csrf_token,
          payload: { diffs, notify },
        });
        try {
          const resp = await fetch(window.location, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
            signal,
          });
          let data = null;
          if (resp.ok) {
            data = await resp.json();
          } else {
            const parsed = await parse_server_failure(resp);
            if (parsed.data) {
              data = parsed.data;
            } else {
              return [null, parsed.message];
            }
          }
          applySaveErrors(data);
          return [
            fmt_save_results(data, cells, human_hours),
            null,
            {
              saved: data.saved || 0,
              idMap: data.id_map || {},
              failedIds: Object.keys(data.errors ?? {}).map((id) => String(id)),
              errorMap: data.errors ?? {},
            },
          ];
        } catch (err) {
          if (err.name == "AbortError") {
            return [null, null];
          }
          return [null, `error: ${err.message}`];
        }
      },
      {
        reload: false,
        onResolved: (_payload, meta = {}) => {
          const failedIds = new Set(meta.failedIds ?? []);
          const errorMap = meta.errorMap ?? {};
          const idMap = meta.idMap ?? {};
          for (const [clientId, serverId] of Object.entries(idMap)) {
            remapCellIdentity(clientId, serverId);
          }
          const successfulCells = targetCells.filter(
            (cell) => !failedIds.has(String(cell.id)),
          );
          for (const cell of successfulCells) {
            const values = applyValues(cell);
            if (values) {
              applyValuesToCell(cell, values);
            }
            commitCellState(cell);
          }
          if (failedIds.size === 0) {
            durationDraftSnapshots.clear();
            modalDurationSlots = 1;
            modalTargetEntries = [];
            modalDurationAnchorKey = null;
          }
          if (activeEntry != null) {
            const activeCell = ensure_cell(activeEntry);
            update_inspector_counts(activeEntry, activeCell, []);
            update_inspector_selection(activeEntry);
            mount_inspector_entry_editor(activeEntry);
            sync_duration_controls(activeEntry, is_entry_editable(activeEntry));
          }
          for (const [failedId, rawSlotErrors] of Object.entries(errorMap)) {
            const failedCell = cells.get(String(failedId));
            if (!failedCell) {
              continue;
            }
            const slotErrors = Array.isArray(rawSlotErrors)
              ? rawSlotErrors
              : [];
            if (rebaseCellFromOverwriteErrors(failedCell, slotErrors)) {
              continue;
            }
            setCellSaveErrors(failedCell, slotErrors);
          }
          update_caption("changed", any_changed());
          update_caption("error", any_invalid());
          update_pending_review_control();
          setBeforeUnload(any_changed());
          sync_row_visibility();
          if (
            activeEntry != null &&
            failedIds.has(String(ensure_cell(activeEntry)?.id ?? ""))
          ) {
            update_inspector_selection(activeEntry);
          }
          if (
            closeInspectorOnSuccess &&
            successfulCells.length === targetCells.length
          ) {
            closeInspector();
          }
        },
      },
    );
  };
  const applyValuesToCell = (cell, values) => {
    if (!cell || !values) {
      return;
    }
    cell.autofilled_group = false;
    if (cell.institute) {
      cell.institute.value = values.institute;
      resetList(cell.institute);
    }
    cell.group.value = values.group;
    cell.update_group_list();
    resetList(cell.group);
    cell.member.value = values.member;
    cell.update_list();
    resetList(cell.member);
    for (const [kind, sr] of Object.entries(cell.sr)) {
      const incoming = values.sr?.[kind];
      if (!incoming) {
        continue;
      }
      if (sr.requested) {
        sr.requested.checked = Boolean(incoming.requested);
      }
      if (sr.handler) {
        sr.handler.value = incoming.requested ? incoming.handler ?? "" : "";
        resetList(sr.handler);
      }
      if (sr.subkind) {
        sr.subkind.value = incoming.subkind ?? sr.subkind.value;
      }
    }
    cell.update();
  };

  const closeInspector = () => {
    syncDurationDraftTargets({ finalize: true });
    if (inspectorDialog && typeof inspectorDialog.hide == "function") {
      inspectorDialog.hide();
    }
    if (inspectorContainer instanceof HTMLElement) {
      inspectorContainer.setAttribute("aria-hidden", "true");
    }
  };
  const submitTemplateDiffs = (diffs, notify = false) => {
    const csrf_token = document.querySelector("#csrf_token").value;
    const body = JSON.stringify({
      csrf_token,
      payload: { diffs, notify },
    });
    result_dialog(async (signal) => {
      try {
        const resp = await fetch(window.location, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        });
        if (resp.ok) {
          const data = await resp.json();
          return [fmt_save_results(data, cells, human_hours), null];
        }
        const parsed = await parse_server_failure(resp);
        if (parsed.data) {
          return [fmt_save_results(parsed.data, cells, human_hours), null];
        }
        return [null, parsed.message];
      } catch (err) {
        if (err.name == "AbortError") {
          return [null, null];
        }
        return [null, `error: ${err.message}`];
      }
    });
  };
  const reviewPendingSave = async () => {
    if (templateEditor) {
      await hydrate_rows(rows, { countForLock: false });
    }
    const issues = collect_review_issues();
    const diffs = [];
    let targetCells = [];
    if (templateEditor) {
      for (const cell of sorted_changed_cells()) {
        const diff = cell.diff();
        if (diff) {
          diffs.push(diff);
        }
      }
    } else {
      const batch = buildDiffBatchFromCells(sorted_changed_cells());
      targetCells = batch.targetCells;
      diffs.push(...batch.diffs);
    }
    if (diffs.length == 0 && issues.length == 0) {
      editor_dialog(
        false,
        false,
        "no pending changes",
        "there are no pending changes or active issues to review",
        null,
        { confirmText: "Close" },
      );
      return;
    }
    const blocking = templateEditor ? any_invalid() : changedInvalid.size > 0;
    const titleText =
      diffs.length > 0 ? "review pending changes" : "review issues";
    const content = build_review_content(issues, diffs, { blocking });
    if (diffs.length == 0 || blocking) {
      editor_dialog(false, false, titleText, content, null, {
        confirmText: "Close",
      });
      return;
    }
    const [showNotifications] = fmt_editor_diffs(
      human_hours,
      templateEditor,
      diffs,
    );
    editor_dialog(
      true,
      showNotifications,
      titleText,
      content,
      (notify) => {
        if (templateEditor) {
          submitTemplateDiffs(diffs, notify);
          return;
        }
        submitDiffBatch(diffs, targetCells, {
          notify,
        });
      },
      {
        confirmText: templateEditor ? "Publish changes" : "Confirm",
        cancelText: "Keep editing",
      },
    );
  };

  const submitSlotSave = () => {
    if (templateEditor) {
      return;
    }
    if (!activeEntry) {
      editor_dialog(
        false,
        false,
        "no selected slot",
        "select a slot to edit or view",
        null,
      );
      return;
    }
    const anchorCell = ensure_cell(activeEntry);
    if (!anchorCell) {
      editor_dialog(
        false,
        false,
        "no selected slot",
        "select a valid slot",
        null,
      );
      return;
    }
    if (!is_entry_editable(anchorCell.elm)) {
      editor_dialog(
        false,
        false,
        "not editable",
        "the selected slot cannot be edited",
        null,
      );
      return;
    }
    const targets = resolve_duration_targets(activeEntry, modalDurationSlots);
    const targetEntries = targets.length > 0 ? targets : [activeEntry];
    const targetCells = [];
    for (const entry of targetEntries) {
      const cell = ensure_cell(entry);
      if (!cell) {
        continue;
      }
      targetCells.push({ entry, cell });
    }
    if (targetCells.length == 0) {
      editor_dialog(
        false,
        false,
        "no selected slot",
        "select a valid slot",
        null,
      );
      return;
    }
    for (const { cell } of targetCells) {
      if (!is_entry_editable(cell.elm)) {
        editor_dialog(
          false,
          false,
          "not editable",
          "all targeted slots must be editable",
          null,
        );
        return;
      }
    }
    const validationErrors = [];
    for (const { entry } of targetCells) {
      validationErrors.push(...readSelectedErrors(entry));
    }
    if (validationErrors.length > 0) {
      editor_dialog(
        false,
        false,
        "outstanding errors",
        "all validation errors must be resolved before submitting",
        null,
      );
      return;
    }
    const anchorValues = readCellValues(anchorCell);
    const saveTargets = targetCells.map(({ cell }) => cell);
    const diffs = saveTargets
      .map((cell) => buildDiffForValues(cell, anchorValues))
      .filter(Boolean);
    if (diffs.length == 0) {
      editor_dialog(
        false,
        false,
        "no changes",
        "there are no changes to submit",
        null,
      );
      return;
    }
    closeInspector();
    submitDiffBatch(diffs, saveTargets, {
      closeInspectorOnSuccess: true,
      applyValues: () => anchorValues,
    });
  };

  if (inspector.review) {
    inspector.review.addEventListener("click", (evt) => {
      evt.preventDefault();
      void reviewPendingSave();
    });
  }

  if (inspector.save) {
    inspector.save.addEventListener("click", (evt) => {
      evt.preventDefault();
      submitSlotSave();
    });
  }

  if (inspectorContainer) {
    for (const closer of inspectorContainer.querySelectorAll(
      "[data-a11y-dialog-hide]",
    )) {
      closer.addEventListener("click", () => {
        if (inspectorDialogOpen()) {
          syncDurationDraftTargets({ finalize: true });
        }
      });
    }
  }

  if (inspector.open) {
    inspector.open.addEventListener("click", async (evt) => {
      evt.preventDefault();
      const selectedRowIndex = Number.isInteger(editor.scheduleGrid?.row())
        ? editor.scheduleGrid.row()
        : 0;
      const selectedColIndex = Number.isInteger(editor.scheduleGrid?.col())
        ? editor.scheduleGrid.col()
        : 0;
      const selectedRow =
        rows[selectedRowIndex] ?? activeEntry?.closest("tr") ?? null;
      if (selectedRow) {
        await hydrate_row(selectedRow);
      }
      const selectedCells = selectedRow?.querySelectorAll("td") ?? [];
      const selectedEntry =
        selectedCells[selectedColIndex]?.querySelector("entry-cell") ??
        activeEntry;
      if (!selectedEntry) {
        set_inspector_action_label(false, false, false);
        if (selectedRow) {
          update_inspector_empty(selectedRow, selectedColIndex);
        } else {
          update_inspector_selection(null);
        }
      } else {
        if (activeEntry && activeEntry !== selectedEntry) {
          activeEntry.dataset.active = "false";
        }
        selectedEntry.dataset.active = "true";
        ensure_cell(selectedEntry);
        activeEntry = selectedEntry;
        update_inspector_selection(selectedEntry);
      }
      const editable = is_entry_editable(selectedEntry);
      sync_duration_controls(selectedEntry, editable);
      if (inspectorDialog) {
        inspectorDialog.show();
      }
      if (inspector.save && editable) {
        inspector.save.hidden = false;
      } else if (inspector.save) {
        inspector.save.hidden = true;
      }
    });
  }
}

function main() {
  enforce_datalists();
  clear_server_errors_on_input();
  setup_auto_confirms();
  wire_home_readonly_toggle();
  wire_home_search_and_show_more();
  wire_editor_expando();
  wire_jump_form();
  editor_grid();
  wire_log_buttons();
  wire_legend_modal();
  wire_inspector_modal();
  wire_cell_editors();
}

export {
  Cell,
  Grid,
  SupportRequestSubForm,
  clear_server_errors_on_input,
  confirmDialog,
  editor_dialog,
  editor_grid,
  enforce_datalists,
  fmt_editor_diffs,
  fmt_log,
  fmt_save_results,
  main,
  parse_schedule_cell_markup,
  result_dialog,
  setup_auto_confirms,
  wire_cell_editors,
  wire_log_buttons,
};
