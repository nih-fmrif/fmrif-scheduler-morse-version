const time_formatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  second: "numeric",
});

// used to sort values in fmt_log
const _fmt_log_order = {
  group: 0,
  researcher: 1,
  used: 2,
  filed_by: 3,
  note: 4,
  fulfilled_by: 5,
  approved: 6,
};

function _fmt_log_entry(k, v) {
  const value = document.createElement(v == null ? "i" : "b");
  if (v == null) {
    value.textContent = "nothing";
    return value;
  }
  switch (k) {
    case "used":
      v = v ? "used" : "unused";
      break;
    case "approved":
      v = v ? "approved" : "unapproved";
      break;
  }
  value.textContent = String(v);
  return value;
}

function _fmt_log_entries(entries) {
  if (entries == null || entries.length == 0) {
    return document.createTextNode("no changes have been logged");
  }
  const out = document.createElement("ul");
  for (const entry of entries) {
    const item = document.createElement("li");
    item.append(` on ${time_formatter.format(new Date(entry.modified))}, `);
    if (entry.by) {
      const by = document.createElement("b");
      by.textContent = String(entry.by);
      item.append(by);
    } else {
      const by = document.createElement("i");
      by.textContent = "unknown";
      item.append(by);
    }
    item.append(" changed ");
    const values = Object.entries(entry.values ?? {});
    const changes = document.createElement("ul");
    if (entry.kind == "main") {
      item.append("the entry:");
    } else {
      item.append(`the ${String(entry.kind)} request:`);
    }

    // sort values by key according to _fmt_log_order.
    values.sort(
      (a, b) =>
        (_fmt_log_order[a[0]] ?? Number.POSITIVE_INFINITY) -
        (_fmt_log_order[b[0]] ?? Number.POSITIVE_INFINITY),
    );

    for (let [k, [Old, New]] of values) {
      const change = document.createElement("li");
      change.append(`set ${k.replace(/_/, " ")} from `);
      change.append(_fmt_log_entry(k, Old));
      change.append(" to ");
      change.append(_fmt_log_entry(k, New));
      changes.append(change);
    }
    item.append(changes);
    out.append(item);
  }
  return out;
}

function _fmt_log_template(template) {
  if (template == null) {
    return null;
  }
  const out = document.createElement("p");
  out.className = "template-log";
  const id = document.createElement("b");
  const label = document.createElement("b");
  id.textContent = String(template.id);
  label.textContent = String(template.label);
  out.append("From template ", id, ": ", label);
  if (template.hidden) {
    const archived = document.createElement("i");
    archived.textContent = "archived";
    out.append(" (", archived, ")");
  }
  out.append(".");
  return out;
}

function fmt_log(data) {
  const out = document.createDocumentFragment();
  const template = _fmt_log_template(data.template);
  if (template != null) {
    out.append(template);
  }
  out.append(_fmt_log_entries(data.entries));
  return out;
}

function fmt_sr_diff(out, k, sr) {
  // count the number of changes in the diff
  // if the count is one, we can present a simpler summary
  // also note whether the subkind changed.
  let n = 0;
  let changesSubkind = false;
  const has = (f) => Number(f != undefined); // 0 if undefined, 1 otherwise
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
    tech: "technologist",
    train: "training",
    med: "medical",
  }[k];
  // for tech requests, include the subkind in the name
  // unless the subkind has changed (per the definition above)
  // since that gets reported on its own
  if (k == "tech" && !changesSubkind) {
    name = `${name} (${sr.effectiveSubkind})`;
  }
  name += " request";

  // format the individual diffs, if they exist
  let requested = null;
  if (sr.requested != undefined) {
    requested = document.createElement("i");
    if (sr.requested) {
      requested.textContent = "filed";
    } else {
      requested.textContent = "canceled";
    }
  }

  let handler = null;
  if (sr.handler != undefined) {
    const [Old, New] = sr.handler;
    handler = document.createDocumentFragment();
    if (New) {
      const by = document.createElement("b");
      by.textContent = String(New);
      handler.append("fulfilled by ", by);
      if (Old) {
        const old = document.createElement("b");
        old.textContent = String(Old);
        handler.append(" (was ", old, ")");
      }
    } else {
      const old = document.createElement("b");
      old.textContent = String(Old);
      handler.append("no longer fulfilled by ", old);
    }
  }

  let subkind = null;
  if (changesSubkind) {
    // only one other option so no need to report old value
    const next = document.createElement("i");
    next.textContent = String(sr.subkind[1]);
    subkind = document.createDocumentFragment();
    subkind.append("changed to ", next);
  }

  // n is at least 1 by construction
  if (n == 1) {
    const dd = document.createElement("dd");
    dd.append(name, " ");
    // only 1 of these isn't the empty string
    if (requested != null) {
      dd.append(requested);
    } else if (handler != null) {
      dd.append(handler);
    } else if (subkind != null) {
      dd.append(subkind);
    }
    out.append(dd);
    return;
  }

  // we have at least 2 changes, use a sub-dl
  const dd = document.createElement("dd");
  const dl = document.createElement("dl");
  const dt = document.createElement("dt");
  dt.textContent = `${name}:`;
  dl.append(dt);
  const push = (node) => {
    if (node != null) {
      const row = document.createElement("dd");
      row.append(node);
      dl.append(row);
    }
  };
  push(requested);
  push(subkind);
  push(handler);
  dd.append(dl);
  out.append(dd);
}

// returns a date as-is but translate a day of week number
// a short week day name
function humanize_date_if_needed(date) {
  if (/^[0-7]$/.test(date)) {
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date];
  }
  return date;
}

function fmt_editor_diffs(human_hours, templateEditor, diffs) {
  const out = document.createElement("dl");
  let notifications = 0;
  const add = (diff, k) => {
    const rec = diff[k];
    if (!rec) {
      return 0;
    }
    const [a, b] = rec;
    const dd = document.createElement("dd");
    const field = String(k);
    const oldValue = String(a ?? "");
    const newValue = String(b ?? "");
    // return if this is notification worthy
    if (a == "") {
      const value = document.createElement("b");
      value.textContent = newValue;
      dd.append(`set ${field} to `, value);
      out.append(dd);
      return 1;
    } else if (b == "") {
      const value = document.createElement("b");
      value.textContent = oldValue;
      dd.append(`cleared ${field} (was `, value, ")");
      out.append(dd);
      return 0;
    } else {
      const newElm = document.createElement("b");
      const oldElm = document.createElement("b");
      newElm.textContent = newValue;
      oldElm.textContent = oldValue;
      dd.append(`set ${field} to `, newElm, " (was ", oldElm, ")");
      out.append(dd);
      return 1;
    }
  };
  for (const diff of diffs) {
    const dt = document.createElement("dt");
    dt.textContent = `${humanize_date_if_needed(diff.date)}: ${
      human_hours[diff.hour]
    }`;
    out.append(dt);
    notifications += add(diff, "institute");
    notifications += add(diff, "group");
    notifications += add(diff, "member");
    for (const k of ["tech", "train", "med"]) {
      const sr = diff[k];
      if (sr) {
        fmt_sr_diff(out, k, sr);
      }
    }
  }
  return [!templateEditor && notifications > 0, out];
}

function fmt_save_errors(data, cells, human_hours) {
  const errors = Object.entries(data.errors ?? []);
  if (errors.length == 0) {
    // serious bug if this ever happens but better to let the user
    // know something than to just stop without indication as to why
    return document.createTextNode(
      "internal error: expected confirmation or errors but got neither",
    );
  }

  const out = document.createDocumentFragment();
  const intro = document.createElement("p");
  if (errors.length > 1) {
    intro.append(`${errors.length} errors prevented this save. `);
  } else {
    intro.append("Save failed for the selected entry. ");
  }
  intro.append("please review and retry.");
  out.append(intro);
  const list = document.createElement("dl");
  const appendBold = (parent, value) => {
    const bold = document.createElement("b");
    bold.textContent = String(value);
    parent.append(bold);
  };
  for (const [id, errs] of errors) {
    const cell = cells.get(id);
    const dt = document.createElement("dt");
    if (cell == null) {
      dt.textContent = `entry ${id}`;
      const dd = document.createElement("dd");
      dd.textContent = "entry not loaded in current view; refresh and retry";
      list.append(dt, dd);
      continue;
    }
    dt.textContent = `${humanize_date_if_needed(cell.date)}: ${
      human_hours[cell.hour]
    }`;
    list.append(dt);
    for (const err of errs) {
      const key = err.key != null ? String(err.key) : "";
      const dd = document.createElement("dd");
      if (err.source || err.message) {
        const source = String(err.source || key || "slot");
        const message = String(
          err.message ?? err.msg ?? err.value ?? "validation error",
        );
        dd.append(`${source}: ${message}`);
        list.append(dd);
        continue;
      }
      switch (err.type) {
        case "revocation":
          dd.append("you no longer have access to edit this device");
          break;

        case "expired":
          dd.append("you missed the submission deadline");
          break;

        case "user-removed":
          dd.append(`you are no longer in ${key} ${String(err.value)}`);
          break;

        case "removed":
          dd.append(`${String(err.value)} is no longer a valid ${key}`);
          break;

        case "overwrote": {
          const expected = err.expected;
          const got = err.got;
          dd.append(
            `${key} overwritten by another user: expected the old value to be `,
          );
          if (expected) {
            appendBold(dd, expected);
          } else {
            dd.append("blank entry");
          }
          dd.append(" got ");
          if (got) {
            appendBold(dd, got);
          } else {
            dd.append("blank entry");
          }
          break;
        }
        case "invalid":
          if (err.value) {
            dd.append(String(err.value));
          } else if (err.msg) {
            dd.append(String(err.msg));
          } else {
            dd.append(`${key || "slot"} is invalid`);
          }
          break;
        default:
          if (err.msg) {
            dd.append(String(err.msg));
          } else {
            dd.append(`${key || "slot"} failed validation`);
          }
          break;
      }
      list.append(dd);
    }
  }
  out.append(list);
  return out;
}

function fmt_save_results(data, cells, human_hours) {
  const errors = Object.entries(data.errors ?? []);
  if (data.saved > 0) {
    const out = document.createDocumentFragment();
    let s = "entry";
    if (data.saved > 1) {
      s = "entries";
    }
    out.append(`${data.saved} ${s} updated`);
    if ("notifications" in data) {
      const list = document.createElement("ul");
      for (const n of data["notifications"]) {
        const item = document.createElement("li");
        const key = String(n.key);
        switch (n.msg) {
          case "address":
            item.append(`no address in database to send ${key} notification`);
            break;

          case "failed":
            item.append(
              `${key} notification failed to send, check server logs`,
            );
            break;

          case "success":
            item.append(`${key} notification sent`);
            break;
        }
        list.append(item);
      }
      out.append(list);
    }
    if (errors.length > 0) {
      out.append(fmt_save_errors(data, cells, human_hours));
    }
    return out;
  }

  return fmt_save_errors(data, cells, human_hours);
}

function parse_schedule_cell_markup(markup) {
  if (typeof markup != "string" || markup.trim() == "") {
    return [];
  }
  const parsed = new DOMParser().parseFromString(
    `<body>${markup}</body>`,
    "text/html",
  );
  const allowedTags = new Set(["entry-cell", "entry-legend"]);
  const safe = [];
  for (const node of parsed.body.childNodes) {
    if (node.nodeType == Node.TEXT_NODE) {
      if (node.textContent.trim() == "") {
        continue;
      }
      throw new Error("schedule payload included unexpected text");
    }
    if (node.nodeType != Node.ELEMENT_NODE) {
      throw new Error("schedule payload included unsupported node type");
    }
    const tag = node.tagName.toLowerCase();
    if (!allowedTags.has(tag)) {
      throw new Error(`schedule payload included disallowed element <${tag}>`);
    }
    safe.push(document.importNode(node, true));
  }
  return safe;
}

export {
  fmt_editor_diffs,
  fmt_log,
  fmt_save_results,
  humanize_date_if_needed,
  parse_schedule_cell_markup,
};
