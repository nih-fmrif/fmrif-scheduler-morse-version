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

function enforce_datalists() {
  const inputs = [...document.querySelectorAll("input[list]")];

  if (inputs.length == 0) {
    return;
  }
  const forms = new Set(inputs.map((elm) => elm.form));

  const datalists = get_datalists();
  if (datalists.size == 0) {
    console.warn("there are inputs with the list attribute but no datalists");
    return;
  }

  const validate_and_normalize = (input) => {
    const dl = datalists.get(input.list.id);
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
    form.addEventListener("submit", (evt) => {
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
  const mo = new MutationObserver((ms) => {
    for (const m of ms) {
      const t = m.target;
      if (t.list != null) {
        // can be null when between lists
        t.setCustomValidity("");
        validate_and_normalize(t);
        t.dispatchEvent(new CustomEvent("list-change"));
      }
    }
  });

  for (const input of inputs) {
    validate_and_normalize(input);
    input.addEventListener("input", (evt) => {
      const t = evt.target;
      // clear invalid flag whenever input is changed.
      t.setCustomValidity("");
      // run validation
      validate_and_normalize(t);
    });
    mo.observe(input, {
      attributes: true,
      attributeFilter: ["list"],
    });
  }
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
    const dialog = new A11yDialog(con);
    dialog.on("show", () => {
      // scroll lock and focus cancel button
      disableBodyScroll(modal);
      cancel.focus();
    });
    dialog.on("hide", (evt) => {
      enableBodyScroll(modal);
      // only true if confirm button was used
      resolve(
        Boolean(evt.target && evt.target.name && evt.target.name == "confirm"),
      );
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

function emit_jump_fallback(direction, row, col, source = "grid") {
  document.dispatchEvent(
    new CustomEvent(JUMP_TO_NEXT_NON_EMPTY_DAY_EVENT, {
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
    window.location.assign(url);
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
  daysInput.addEventListener("input", onInput);
  jumpForm.addEventListener("submit", (evt) => {
    evt.preventDefault();
    applyJump();
  });
  jumpForm.dataset.jsReady = "true";
}

const base = json_or(document.querySelector("#app-root").innerText, "/");

async function loadLog(id, template, signal) {
  try {
    const resp = await fetch(`${base}json/v1/log/${id}-${template}`, {
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
  trigger.addEventListener("click", (evt) => {
    evt.preventDefault();
    dialog.show();
  });
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
    return this.cells[row].length - 1;
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
    const row = this.row();
    const nextCol = this.findNextNonEmptyCol(-1, row);
    if (nextCol !== null) {
      return this.focus(row, nextCol);
    }
    emit_jump_fallback(-1, row, this.col());
    return true;
  }
  right() {
    const row = this.row();
    const nextCol = this.findNextNonEmptyCol(1, row);
    if (nextCol !== null) {
      return this.focus(row, nextCol);
    }
    emit_jump_fallback(1, row, this.col());
    return true;
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
  focus(row, col, force = false) {
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
    this.scrollIntoView(row, col);
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
      block: "center",
      inline: "center",
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

  // we use these when handling tab from within the grid
  const [focusableBefore, focusableAfter] = focusables_around(container);

  // move focus to selected item in grid in the next microtask
  const focusContainer = () => {
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

  // if we click inside the grid without changing focus,
  // focus the correct cell
  editor.addEventListener("click", (evt) => {
    const t = evt.target;
    if (t.matches("td")) {
      grid.focus(t.dataset.row, t.dataset.col);
      evt.preventDefault();
    }
  });

  container.addEventListener("keydown", (evt) => {
    if (evt.isComposing || evt.keyCode == 229) {
      return;
    }

    // we only want to intercept esc and tab when we're in a cell
    if (grid.isOpen()) {
      switch (evt.key) {
        case "Esc":
        case "Escape":
          grid.focus(...grid.pos(), true);
          break;

        case "Tab": {
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
            evt.preventDefault();
          }
          break;
        }
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
        {
          const selected = grid.selectedCell();
          if (selected == null) {
            break;
          }
          const first = selected.querySelector(
            ":is(input, button):not(:disabled)",
          );
          if (first != null) {
            first.focus();
          }
        }
        break;

      case "Tab":
        if (evt.shiftKey) {
          focusableBefore.focus();
        } else {
          focusableAfter.focus();
        }
        break;

      default:
        return;
    }
    evt.preventDefault();
  });
  grid.select(...grid.pos());
  editor.setAttribute("role", "grid");
  container.classList.add("js-grid");
}

function editor_dialog(save, showNotifications, titleText, content, then) {
  const con = document.getElementById("save-dialog-container");
  const modal = con.querySelector(".dialog-box-container");
  const title = con.querySelector("#save-dialog-title");
  const body = con.querySelector(".dialog-content-inner");
  const cancel = con.querySelector("button[name=cancel]");
  const notificationsCon = con.querySelector(".dialog-form input-set");
  const notifications = notificationsCon.querySelector("#send-notifications");
  title.innerText = titleText;
  replaceNodeContent(body, content);
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
  dialog.on("hide", (evt) => {
    enableBodyScroll(modal);
    // only follow continuation if confirm button was used
    if (evt.target && evt.target.name && evt.target.name == "confirm" && then) {
      then(notifications.checked);
    }
    // reset template
    title.innerText = "";
    body.replaceChildren();
    cancel.hidden = true;
    notificationsCon.hidden = true;
  });
  dialog.show();
}

function result_dialog(proc) {
  const con = document.getElementById("result-dialog-container");
  const modal = con.querySelector(".dialog-box-container");
  const body = con.querySelector(".dialog-content-inner");
  const dialog = new A11yDialog(con);
  const abort = new AbortController();
  let changesSaved = false;
  dialog.on("show", async () => {
    disableBodyScroll(modal);

    const [data, err] = await proc(abort.signal);
    con.classList.add("dialog-loaded");
    announce("results available");
    if (err != null) {
      body.innerText = err;
      return;
    }
    replaceNodeContent(body, data);
    changesSaved = true;
  });
  dialog.on("hide", () => {
    enableBodyScroll(modal);
    con.classList.remove("dialog-loaded");
    body.replaceChildren();
    abort.abort();
    if (changesSaved) {
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
  elm.setAttribute("list", elm.list.id);
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

    this.orig = {
      requested: to_bool(this.requested.dataset.orig),
      handler: this.handler.dataset.orig,
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
    if (
      this.requested.checked &&
      this.subkind != null &&
      this.orig.subkind != this.subkind.value
    ) {
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
    if (this.parent.locked) {
      return false;
    }
    // past entries are not editable (past handles users with edit_any)
    if (this.parent.past) {
      return false;
    }
    // editable if part of an editable cell and there exists someone to fulfill the request
    if (this.members.size > 0 && this.parent.editable) {
      return true;
    }
    // if nothing else hit, the request editable if the current user
    // can field this kind of request.
    return this.perms[this.kind];
  }
  get handler_editable() {
    // each kind has the same name as the corresponding perm.
    // NB. while this is sometimes redundant this.editable short-circuits
    // and is not redundant in those cases.
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
    resetList(this.handler);
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
    this.institute = elm.querySelector("input[id^=ins-]");
    this.group = elm.querySelector("input[id^=grp-]");
    this.member = elm.querySelector("input[id^=mem-]");
    this.legend = elm.querySelector("entry-legend");
    this.resetBtn = elm.querySelector("button[data-reset]");
    this.summaryKind = elm.dataset.summaryKind ?? "schedule";
    this.summaryPrimary = elm.querySelector(".entry-summary-primary");
    this.summarySecondary = elm.querySelector(".entry-summary-secondary");
    this.summaryTertiary = elm.querySelector(".entry-summary-tertiary");

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

    // gather any support requests
    const subforms = [...elm.querySelectorAll("fieldset[data-sr]")];
    const kv = subforms.map((sr) => [
      sr.dataset.sr,
      new SupportRequestSubForm(sr, this, cfg),
    ]);
    this.sr = Object.fromEntries(kv);
    this.update_summary();

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

    this.elm.dataset.canEdit = this.editable;
    this.resetBtn.disabled = !this.editable;

    this.resetBtn.addEventListener("click", (evt) => {
      evt.preventDefault();
      this.reset();
      this.update();
    });
    this.elm.addEventListener("input", () => {
      this.update();
    });
    this.member.addEventListener("list-change", () => {
      this.update();
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
    return (
      this.orig.group != this.group.value ||
      this.orig.member != this.member.value
    );
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
  get past() {
    // users with edit_any are not bound by this concept
    if (this.perms.edit_any) {
      return false;
    }
    return this.old;
  }
  get editable() {
    if (this.locked) {
      return false;
    }
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
      id: this.id,
      date: this.date,
      hour: this.hour,
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
      resetList(this.institute);
    }
    this.group.value = this.orig.group;
    resetList(this.group);
    this.member.value = this.orig.member;
    resetList(this.member);
    for (const sr of Object.values(this.sr)) {
      sr.reset();
    }
    this.update_list();
    this.update_summary();
    this.fire_change();
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
    if (this.member.list.id != list) {
      this.member.setAttribute("list", list);
    }
  }
  update_swatch() {
    const classPrefix = "swatch-group-";
    for (const cls of [...this.legend.classList]) {
      if (cls.startsWith(classPrefix)) {
        this.legend.classList.remove(cls);
      }
    }
    const token = this.colors[this.group.value]
      ? cssToken(this.group.value)
      : "none";
    this.legend.classList.add(`${classPrefix}${token}`);
  }
  update_summary() {
    if (
      !this.summaryPrimary &&
      !this.summarySecondary &&
      !this.summaryTertiary
    ) {
      return;
    }
    const group = this.group.value || "open";
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
  fire_change() {
    this.elm.dispatchEvent(
      new CustomEvent("cell_change", {
        bubbles: true,
        detail: this,
      }),
    );
  }
  update() {
    this.update_list();
    this.update_swatch();
    this.update_summary();
    this.elm.dataset.changed = this.changed;
    this.elm.dataset.error = this.changed && this.invalid;
    this.fire_change();
  }
  resetAndLock() {
    // this cell was submitted to and rejected by the server
    // reset it to default state and prevent further changes
    this.reset();
    this.locked = true;
    this.elm.dataset.canEdit = false;
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
  const scheduleWindow = remoteScheduleRows
    ? {
        start: parse_ymd(scheduleLoad.start),
        chunkDays: Number.parseInt(scheduleLoad.days, 10) || 7,
        totalDays: Number.parseInt(scheduleLoad.days, 10) || 7,
        endpoint: scheduleLoad.endpoint,
      }
    : {
        start: null,
        chunkDays: 7,
        totalDays: 0,
        endpoint: "",
      };
  if (Number.isNaN(scheduleWindow.totalDays) || scheduleWindow.totalDays < 1) {
    scheduleWindow.totalDays = 7;
  }
  if (scheduleWindow.chunkDays < 1 || scheduleWindow.chunkDays > 31) {
    scheduleWindow.chunkDays = 7;
  }
  scheduleWindow.chunkDays = Math.min(
    31,
    Math.max(1, scheduleWindow.chunkDays),
  );

  const nextDayEndpoint = scheduleWindow.endpoint
    ? scheduleWindow.endpoint.replace("/schedule-rows", "/schedule-next-day")
    : "";
  const jumpPrevDayBtn = document.querySelector("#jump-prev-non-empty");
  const jumpNextDayBtn = document.querySelector("#jump-next-non-empty");

  // if this is missing, we're on a template page so everything is true
  const perms = json_from_script_or("user-perms", {
    edit: true,
    edit_any: true,
    medical: true,
    tech: true,
    training: true,
  });

  // if this is missing we're on a template page so edit_any is true and it's irrelevant
  const membership = new Set(json_from_script_or("user-groups", []));
  membership.add(""); // consider every one a member of the null group

  const device_groups = new Set(json_from_script_or("device-groups", []));
  const colors = json_from_script_or("group-colors", {});
  const human_hours = json_from_script_or("human-hours", null);

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
    perms,
    membership,
    device_groups,
    schedulable_groups,
    colors,
    sr_members: {
      tech: tech_members,
      train: train_members,
      med: med_members,
    },
  };

  // keep track of changed and invalid cells
  const cells = new Map();
  const gridCells = [];
  const changed = new Set();
  const any_changed = () => Boolean(changed.size);
  const invalid = new Set();
  const any_invalid = () => Boolean(invalid.size);
  const changedInvalid = new Set();

  // keep caption in sync with cell updates
  const caption = document.querySelector("#caption");
  const update_caption = (which, bool) => {
    caption.dataset[which] = from_bool(bool);
  };
  const inspector = {
    target: document.querySelector(".editor-inspector-target"),
    summary: document.querySelector(".editor-inspector-summary"),
    mode: document.querySelector(".editor-inspector-mode"),
    pending: document.querySelector(".editor-inspector-pending"),
    errors: document.querySelector(".editor-inspector-errors"),
    detailTarget: document.querySelector(".editor-inspector-detail-target"),
    detailSummary: document.querySelector(".editor-inspector-detail-summary"),
    detailMode: document.querySelector(".editor-inspector-detail-mode"),
    detailPending: document.querySelector(".editor-inspector-detail-pending"),
    detailErrors: document.querySelector(".editor-inspector-detail-errors"),
  };
  const sync_inspector_modal = () => {
    if (inspector.detailTarget && inspector.target) {
      inspector.detailTarget.innerText = inspector.target.innerText;
    }
    if (inspector.detailSummary && inspector.summary) {
      inspector.detailSummary.innerText = inspector.summary.innerText;
    }
    if (inspector.detailMode && inspector.mode) {
      inspector.detailMode.innerText = inspector.mode.innerText;
    }
    if (inspector.detailPending && inspector.pending) {
      inspector.detailPending.innerText = inspector.pending.innerText;
    }
    if (inspector.detailErrors && inspector.errors) {
      inspector.detailErrors.innerText = inspector.errors.innerText;
    }
  };
  const loadStatus = document.querySelector("#editor-load-status");
  const rows = [...container.querySelectorAll("tr[data-hour]")];
  const rowsByHour = new Map(rows.map((row) => [row.dataset.hour, row]));
  let loadErrorMessage = "";
  const headerCells = [
    ...scrollContainer.querySelectorAll("thead th:not(:first-child)"),
  ];
  const formatHeaderLabel = (date) => {
    if (!(date instanceof Date)) {
      return "";
    }
    return `${ymd(date)} ${date.toLocaleDateString("en-US", {
      weekday: "short",
      timeZone: "UTC",
    })}`;
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

  const syncHeaderDates = () => {
    const first = startDate();
    if (first == null) {
      return;
    }
    for (let i = 0; i < headerCells.length; i += 1) {
      const date = add_days(first, i);
      const th = headerCells[i];
      if (!th) {
        continue;
      }
      th.innerText = formatHeaderLabel(date);
      th.dataset.date = ymd(date);
    }
  };

  syncHeaderDates();

  const dayLabelForCol = (col) => {
    const date = dateForCol(col);
    if (date == null) {
      return "";
    }
    return formatHeaderLabel(date);
  };
  let activeEntry = null;

  const rebuildCells = () => {
    gridCells.length = 0;
    for (const row of rows) {
      const rowIndex = gridCells.push([]) - 1;
      row.querySelectorAll("td").forEach((col) => {
        const colIndex = gridCells[rowIndex].push(col) - 1;
        col.setAttribute("tabindex", "-1");
        col.setAttribute("role", "gridcell");
        col.dataset.row = rowIndex;
        col.dataset.col = colIndex;
      });
    }
    if (editor?.scheduleGrid != null) {
      editor.scheduleGrid.cells = gridCells;
    }
  };

  for (const row of rows) {
    if (!remoteScheduleRows || row.querySelector("entry-cell")) {
      row.dataset.loaded = "true";
    } else {
      row.dataset.loaded = "false";
    }
  }

  const update_inspector_counts = () => {
    if (inspector.pending) {
      const suffix = changed.size == 1 ? "" : "s";
      inspector.pending.innerText = `${changed.size} change${suffix}`;
    }
    if (inspector.errors) {
      const suffix = changedInvalid.size == 1 ? "" : "s";
      inspector.errors.innerText = `${changedInvalid.size} error${suffix}`;
    }
    sync_inspector_modal();
  };

  const update_inspector_selection = (entry) => {
    if (!entry) {
      return;
    }
    if (inspector.target) {
      const date = humanize_date_if_needed(entry.dataset.date ?? "");
      const hour =
        human_hours?.[entry.dataset.hour] ?? entry.dataset.hour ?? "";
      inspector.target.innerText = `${date}, ${hour}`;
    }
    if (inspector.summary) {
      const primary =
        entry.querySelector(".entry-summary-primary")?.innerText ?? "open";
      const secondary =
        entry.querySelector(".entry-summary-secondary")?.innerText ??
        "unassigned";
      const tertiary = entry.querySelector(
        ".entry-summary-tertiary",
      )?.innerText;
      const pieces = [primary, secondary];
      if (tertiary) {
        pieces.push(tertiary);
      }
      inspector.summary.innerText = pieces.join(" | ");
    }
    if (inspector.mode) {
      if (entry.dataset.locked == "true") {
        inspector.mode.innerText = "locked";
      } else if (entry.dataset.canEdit == "true") {
        inspector.mode.innerText = "editable";
      } else {
        inspector.mode.innerText = "read only";
      }
    }
    sync_inspector_modal();
  };

  const update_inspector_empty = (row, col) => {
    if (!row) {
      return;
    }
    if (inspector.target) {
      const hour = human_hours?.[row.dataset.hour] ?? row.dataset.hour ?? "";
      const day = dayLabelForCol(col);
      inspector.target.innerText = `${day}, ${hour}`.replace(/^,\s*/, "");
    }
    if (inspector.summary) {
      inspector.summary.innerText = "no sched entry for this slot";
    }
    if (inspector.mode) {
      inspector.mode.innerText = "read only";
    }
    sync_inspector_modal();
  };

  const update_load_status = () => {
    if (!loadStatus) {
      return;
    }
    if (loadErrorMessage) {
      loadStatus.innerText = `error loading schedule rows: ${loadErrorMessage}`;
      loadStatus.dataset.state = "error";
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

  const addWindowColumns = (start, direction, chunk) => {
    if (chunk <= 0) {
      return;
    }
    const header = scrollContainer.querySelector("thead tr");
    if (header == null) {
      return;
    }

    for (let i = 0; i < chunk; i++) {
      const date = add_days(start, i);
      const th = document.createElement("th");
      th.innerText = formatHeaderLabel(date);
      th.dataset.date = ymd(date);
      if (direction > 0) {
        header.append(th);
      } else {
        header.prepend(th);
      }
    }

    for (const row of rows) {
      if (!row) {
        continue;
      }
      for (let i = 0; i < chunk; i++) {
        const td = document.createElement("td");
        td.dataset.placeholder = "true";
        if (direction > 0) {
          row.append(td);
        } else {
          row.prepend(td);
        }
      }
    }

    rebuildCells();
    for (const row of rows) {
      row.dataset.loaded = "false";
      row.dataset.hydrated = "false";
    }
    updateHeaderCells();
    syncHeaderDates();
  };

  const updateHeaderCells = () => {
    headerCells.length = 0;
    headerCells.push(
      ...scrollContainer.querySelectorAll("thead th:not(:first-child)"),
    );
  };

  let leftEdgeAvailable = null;
  let rightEdgeAvailable = null;
  let windowShiftInFlight = null;
  let previousSelectedCol = null;

  const canExpandWindow = async (direction) => {
    if (!remoteScheduleRows) {
      return false;
    }
    if (direction === -1) {
      if (leftEdgeAvailable === false) {
        return false;
      }
    } else if (rightEdgeAvailable === false) {
      return false;
    }

    const start = scheduleWindow.start;
    if (start == null || nextDayEndpoint == "") {
      return false;
    }

    const probeDate = direction === 1 ? visibleEndDate() ?? start : start;

    const url = new URL(nextDayEndpoint, window.location.href);
    url.searchParams.set("start", ymd(probeDate));
    url.searchParams.set("direction", String(direction));

    try {
      const resp = await fetch(url.toString(), {
        headers: {
          Accept: "application/json",
        },
      });
      if (!resp.ok) {
        throw new Error(`api returned ${resp.status}`);
      }
      const data = await resp.json();
      const next = data?.date ?? null;
      if (direction === -1) {
        leftEdgeAvailable = next != null;
      } else {
        rightEdgeAvailable = next != null;
      }
      return next != null;
    } catch (_err) {
      return false;
    }
  };

  const expandWindow = async (direction) => {
    void direction;
    // Keep the visible day count fixed; jumps recenter via navigateToDateWindow.
    return false;
  };

  const maybeExpandAroundCol = (col) => {
    if (!remoteScheduleRows || Number.isNaN(col) || windowShiftInFlight) {
      return;
    }
    if (previousSelectedCol == null) {
      previousSelectedCol = col;
      return;
    }
    const movingDirection =
      col > previousSelectedCol ? 1 : col < previousSelectedCol ? -1 : 0;
    previousSelectedCol = col;
    if (movingDirection == 0) {
      return;
    }
    const leftEdgeCol = 1;
    const rightEdgeCol = Math.max(0, scheduleWindow.totalDays - 2);
    const shouldExpandLeft = movingDirection < 0 && col <= leftEdgeCol;
    const shouldExpandRight = movingDirection > 0 && col >= rightEdgeCol;
    if (!shouldExpandLeft && !shouldExpandRight) {
      return;
    }
    windowShiftInFlight = expandWindow(movingDirection);
    windowShiftInFlight.finally(() => {
      windowShiftInFlight = null;
    });
  };

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
  const navigateToDateWindow = (targetDate) => {
    if (!(targetDate instanceof Date)) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    params.set("start", ymd(targetDate));

    const daysInput = document.querySelector(
      'nav.jump-form input[name="days"]',
    );
    const parsedDays = Number.parseInt(daysInput?.value ?? "", 10);
    const safeDays = Number.isNaN(parsedDays)
      ? scheduleWindow.chunkDays
      : Math.min(31, Math.max(1, parsedDays));
    params.set("days", String(safeDays));
    window.location.assign(`${window.location.pathname}?${params.toString()}`);
  };

  const load_rows = async (hoursToLoad) => {
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
      try {
        for (const windowRange of rangeStarts) {
          const url = new URL(scheduleWindow.endpoint, window.location.href);
          const rangeStart = add_days(scheduleWindow.start, windowRange.offset);
          url.searchParams.set("start", ymd(rangeStart));
          url.searchParams.set("days", String(windowRange.days));
          url.searchParams.set("hours", chunk.join(","));

          const resp = await fetch(url.toString(), {
            headers: {
              Accept: "application/json",
            },
          });
          if (!resp.ok) {
            throw new Error(`api returned ${resp.status}`);
          }

          const data = await resp.json();
          const payloadRows = Array.isArray(data.rows) ? data.rows : [];
          const payloadByHour = new Map(
            payloadRows.map((row) => [String(row.hour), row]),
          );

          for (const hour of chunk) {
            const row = rowsByHour.get(hour);
            if (!row) {
              continue;
            }
            const payload = payloadByHour.get(hour);
            const slots = [...row.querySelectorAll("td")];
            const payloadCells = Array.isArray(payload?.cells)
              ? payload.cells
              : [];
            for (
              let i = 0;
              i < windowRange.days && i + windowRange.offset < slots.length;
              i += 1
            ) {
              const markup =
                typeof payloadCells[i] == "string" ? payloadCells[i] : "";
              slots[i + windowRange.offset].replaceChildren(
                ...parse_schedule_cell_markup(markup),
              );
            }
            row.dataset.loading = "false";
            row.querySelectorAll("entry-cell").forEach((entry) => {
              if (!("active" in entry.dataset)) {
                entry.dataset.active = "false";
              }
            });
          }
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
    update_inspector_counts();
    return cell;
  };

  const hydrate_rows = async (targets) => {
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
      await load_rows(hours);
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
    update_load_status();
    if (activeEntry == null) {
      const grid = editor.scheduleGrid;
      if (!grid) {
        return;
      }
      for (let rowIndex = 0; rowIndex < grid.cells.length; rowIndex += 1) {
        const rowCells = grid.cells[rowIndex];
        for (let colIndex = 0; colIndex < rowCells.length; colIndex += 1) {
          const entry = rowCells[colIndex]?.querySelector("entry-cell");
          if (!entry) {
            continue;
          }
          grid.focus(rowIndex, colIndex);
          return;
        }
      }
    }
  };

  const hydrate_row = async (row) => {
    await hydrate_rows([row]);
  };

  const initialRows = rows.filter((row) => !row.hidden).slice(0, 4);
  void hydrate_rows(initialRows);

  if ("IntersectionObserver" in window) {
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
        root: scrollContainer,
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
        grid.focus(row, col + direction);
        return;
      }

      const movedIntoWindow = await ensureWindowContainsDate(nextDate);
      if (!movedIntoWindow) {
        navigateToDateWindow(nextDate);
        return;
      }

      const windowStart = startDate();
      if (windowStart == null) {
        return;
      }
      const targetCol = days_since(windowStart, nextDate);
      grid.focus(row, targetCol);
    } finally {
      jumpLookupInFlight = false;
    }
  });

  if (editorTable) {
    editorTable.addEventListener("grid_selection", (evt) => {
      const row = parseInt(evt.detail?.row, 10);
      const col = parseInt(evt.detail?.col, 10);
      const entry = evt.detail?.entry;
      maybeExpandAroundCol(col);
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
      expandOnScroll();
    });
  });

  const expando = document.querySelector("#expando");
  if (expando) {
    expando.addEventListener("click", () => {
      const newlyVisible = rows
        .filter((row) => !row.hidden && row.dataset.hydrated != "true")
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

  container.addEventListener("cell_change", (evt) => {
    const cell = evt.detail;

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

    // add the beforeunload handler if there are changes
    // and remove it if not
    setBeforeUnload(any_changed());
    update_inspector_counts();
    if (activeEntry != null && activeEntry.dataset.id == cell.id) {
      update_inspector_selection(activeEntry);
    }
  });

  const apply = document.querySelector("#apply");
  apply.disabled = false;
  apply.addEventListener("click", (evt) => {
    evt.preventDefault();
    if (!any_changed()) {
      editor_dialog(
        false,
        false,
        "no changes",
        "there are no changes to submit",
        null,
      );
    } else if (changedInvalid.size > 0) {
      editor_dialog(
        false,
        false,
        "outstanding errors",
        "all errors must be resolved in updated entries before submitting",
        null,
      );
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
      let [notifications, summary] = fmt_editor_diffs(
        human_hours,
        templateEditor,
        diffs,
      );
      editor_dialog(
        true,
        notifications,
        "publish changes",
        summary,
        (notify) => {
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
              if (!resp.ok) {
                return [null, `error: unexpected ${resp.status} from server`];
              }
              const data = await resp.json();
              // the error is for severe errors like networking errors
              // validation errors are not counted here as they are
              // considered a normal response
              return [fmt_save_results(data, cells, human_hours), null];
            } catch (err) {
              if (err.name == "AbortError") {
                return [null, null];
              }
              return [null, `error: ${err.message}`];
            }
          });
        },
      );
    }
  });
}

function main() {
  enforce_datalists();
  clear_server_errors_on_input();
  setup_auto_confirms();
  wire_home_readonly_toggle();
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
