import { getAppNotifier } from "../notifications.js";

function text(value) {
  if (value == null) {
    return "";
  }
  return String(value);
}

function normalizeFuzzy(value) {
  return text(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function subsequenceGap(token, candidate) {
  let tokenIndex = 0;
  let lastMatch = -1;
  let gapPenalty = 0;

  for (let idx = 0; idx < candidate.length; idx += 1) {
    if (candidate[idx] !== token[tokenIndex]) {
      continue;
    }
    if (lastMatch >= 0) {
      gapPenalty += idx - lastMatch - 1;
    }
    lastMatch = idx;
    tokenIndex += 1;
    if (tokenIndex >= token.length) {
      return gapPenalty;
    }
  }

  return -1;
}

function fuzzyScore(query, entity) {
  const normalizedQuery = normalizeFuzzy(query);
  if (normalizedQuery === "") {
    return 0;
  }

  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);
  const candidateWords = normalizeFuzzy(`${entity.id} ${entity.label}`);
  const candidateCompact = candidateWords.replace(/\s+/g, "");
  if (candidateWords === "") {
    return -1;
  }

  let score = 0;
  for (const token of tokens) {
    if (token.length === 0) {
      continue;
    }

    if (candidateWords === token || candidateCompact === token) {
      score += 1400;
      continue;
    }

    if (
      candidateWords.startsWith(token) ||
      candidateCompact.startsWith(token)
    ) {
      score += 1100 - Math.min(candidateWords.length, 160);
      continue;
    }

    const exactIndex = candidateWords.indexOf(token);
    if (exactIndex >= 0) {
      score += 850 - Math.min(exactIndex, 350);
      continue;
    }

    const compactIndex = candidateCompact.indexOf(token);
    if (compactIndex >= 0) {
      score += 760 - Math.min(compactIndex, 350);
      continue;
    }

    const gap = subsequenceGap(token, candidateCompact);
    if (gap < 0) {
      return -1;
    }
    score += 450 - Math.min(gap, 220);
  }

  score -= Math.floor(candidateWords.length / 12);
  return score;
}

function rankEntities(query, entities) {
  const normalizedQuery = normalizeFuzzy(query);
  if (normalizedQuery === "") {
    return entities.slice();
  }

  const ranked = [];
  for (const entity of entities) {
    const score = fuzzyScore(normalizedQuery, entity);
    if (score < 0) {
      continue;
    }
    ranked.push({ entity, score });
  }

  ranked.sort((a, b) => {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    return text(a.entity.label).localeCompare(text(b.entity.label));
  });

  return ranked.map((entry) => entry.entity);
}

const ENTITY_SUGGESTION_LIMIT = 200;
const ENTITY_SUGGESTION_INCREMENT = 200;
const RBAC_SHOW_MORE_DEFAULT_LIMIT = 10;
const RBAC_SHOW_MORE_INCREMENT = 20;
const RBAC_SHOW_MORE_MAX_LIMIT = 200;
const MATRIX_VISIBLE_ROW_LIMIT = RBAC_SHOW_MORE_DEFAULT_LIMIT;
const MATRIX_VISIBLE_ROW_INCREMENT = RBAC_SHOW_MORE_INCREMENT;
const MATRIX_VISIBLE_ROW_MAX_LIMIT = RBAC_SHOW_MORE_MAX_LIMIT;
const FILTER_DEBOUNCE_MS = 140;

function debounce(callback, delay) {
  let timer = null;
  return (...args) => {
    if (timer !== null) {
      window.clearTimeout(timer);
    }
    timer = window.setTimeout(() => {
      timer = null;
      callback(...args);
    }, delay);
  };
}

function setStatus(node, message, state = "info") {
  node.textContent = message;
  node.dataset.state = state;
}

function makeLink(label, href) {
  const target = text(href).trim();
  if (target === "") {
    const span = document.createElement("span");
    span.textContent = label;
    return span;
  }
  const anchor = document.createElement("a");
  anchor.textContent = label;
  anchor.href = target;
  return anchor;
}

function renderGraphSide(container, nodes, direction, moreCount) {
  container.replaceChildren();

  if (!Array.isArray(nodes) || nodes.length === 0) {
    const row = document.createElement("li");
    row.className = "none";
    row.textContent = "none";
    container.append(row);
    return;
  }

  nodes.forEach((node) => {
    const row = document.createElement("li");
    const arrow = document.createElement("span");
    arrow.className = "rbac-arrow";
    arrow.textContent = "->";
    arrow.setAttribute("aria-hidden", "true");

    const info = document.createElement("div");
    info.className = "rbac-node";
    info.append(makeLink(text(node.label), text(node.href)));
    if (node.meta) {
      const meta = document.createElement("small");
      meta.textContent = text(node.meta);
      info.append(meta);
    }

    if (direction === "sources") {
      row.append(info, arrow);
    } else {
      row.append(arrow, info);
    }
    container.append(row);
  });

  if (Number(moreCount) > 0) {
    const more = document.createElement("li");
    more.className = "rbac-more";
    more.textContent = `...and ${moreCount} more`;
    container.append(more);
  }
}

function formatAuditWhen(value) {
  const raw = text(value);
  if (raw === "") {
    return "";
  }
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return raw;
  }
  return parsed.toLocaleString();
}

function renderAuditEvents(listNode, noteNode, payload, scope, entity) {
  listNode.replaceChildren();
  const events = Array.isArray(payload?.events) ? payload.events : [];

  if (entity) {
    noteNode.textContent = `Showing up to ${text(
      payload?.limit || events.length || 0,
    )} RBAC events for ${scope} "${entity}".`;
  } else {
    noteNode.textContent = "Showing recent RBAC events.";
  }

  if (events.length === 0) {
    const empty = document.createElement("li");
    empty.className = "none";
    empty.textContent = "No RBAC audit events found for this selection.";
    listNode.append(empty);
    return;
  }

  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = "rbac-audit-item";

    const summary = document.createElement("p");
    summary.className = "rbac-audit-summary";
    const ip = text(event.ip);
    summary.textContent = `${text(event.action)} by ${text(event.actor)}${
      ip === "" ? "" : ` (${ip})`
    } via ${text(event.how)}`;

    const details = document.createElement("p");
    details.className = "rbac-audit-details";
    details.textContent = text(event.what);

    const meta = document.createElement("p");
    meta.className = "rbac-audit-meta";
    const whenText = formatAuditWhen(event.when);
    meta.textContent =
      whenText === ""
        ? text(event.where)
        : `${whenText} - ${text(event.where)}`;

    item.append(summary, details, meta);
    listNode.append(item);
  });
}

function renderScopeOptions(select, scopes, selected) {
  select.replaceChildren();
  scopes.forEach((scope) => {
    const option = document.createElement("option");
    option.value = text(scope.id);
    option.textContent = text(scope.label);
    if (scope.id === selected) {
      option.selected = true;
    }
    select.append(option);
  });
}

function renderEntitySuggestions(
  list,
  input,
  entities,
  activeIndex,
  selected,
  showMore = false,
) {
  list.replaceChildren();
  const expanded = entities.length > 0;
  input.setAttribute("aria-expanded", expanded ? "true" : "false");
  if (!expanded) {
    input.removeAttribute("aria-activedescendant");
    return;
  }

  let activeOptionId = "";
  entities.forEach((entity) => {
    const index = list.childElementCount;
    const item = document.createElement("li");
    const optionId = `rbac-entity-option-${index}`;
    item.id = optionId;
    item.setAttribute("role", "option");
    item.dataset.entityId = text(entity.id);
    item.setAttribute(
      "aria-selected",
      entity.id === selected ? "true" : "false",
    );

    const name = document.createElement("span");
    name.textContent = text(entity.label);
    item.append(name);

    if (entity.id !== entity.label) {
      const meta = document.createElement("small");
      meta.textContent = text(entity.id);
      item.append(meta);
    }

    if (index === activeIndex) {
      item.classList.add("active");
      activeOptionId = optionId;
    }
    list.append(item);
  });

  if (showMore) {
    const moreItem = document.createElement("li");
    moreItem.className = "rbac-entity-more";
    moreItem.setAttribute("role", "button");
    moreItem.setAttribute("data-show-more", "1");
    moreItem.textContent = "show more results";
    list.append(moreItem);
  }

  if (activeOptionId !== "") {
    input.setAttribute("aria-activedescendant", activeOptionId);
  } else {
    input.removeAttribute("aria-activedescendant");
  }
}

function syncUrl(scope, entity, includeInactive) {
  const url = new URL(window.location.href);
  url.searchParams.set("scope", scope);
  if (entity) {
    url.searchParams.set("entity", entity);
  } else {
    url.searchParams.delete("entity");
  }
  if (includeInactive) {
    url.searchParams.set("active", "1");
  } else {
    url.searchParams.delete("active");
  }
  url.searchParams.delete("create");
  window.history.replaceState({}, "", url);
}

function filterMatrixRows(
  tableBody,
  query,
  visibleLimit = MATRIX_VISIBLE_ROW_LIMIT,
) {
  const normalized = normalizeFuzzy(query);
  const rows = Array.from(tableBody.querySelectorAll("tr"));
  const limit = Math.max(0, Math.floor(Number(visibleLimit) || 0));
  const matches = rows.map((row) => {
    const haystack = normalizeFuzzy(row.dataset.search || "");
    return normalized === "" || haystack.includes(normalized);
  });

  const matchingCount = matches.filter(Boolean).length;
  let visibleCount = 0;
  rows.forEach((row, index) => {
    const show = matches[index] && (limit === 0 || visibleCount < limit);
    row.dataset.hidden = show ? "0" : "1";
    if (show) {
      visibleCount += 1;
    }
  });
  return {
    totalCount: rows.length,
    matchingCount,
    visibleCount,
  };
}

function matrixFilterSettings(matrix, layout) {
  const configuredPlaceholder = text(matrix.filter_placeholder).trim();
  if (layout === "keyvalue") {
    return {
      field: "",
      placeholder:
        configuredPlaceholder !== "" ? configuredPlaceholder : "filter setting",
    };
  }

  const columns = Array.isArray(matrix.columns) ? matrix.columns : [];
  if (columns.length === 0) {
    return {
      field: "",
      placeholder:
        configuredPlaceholder !== "" ? configuredPlaceholder : "filter rows",
    };
  }

  const configuredField = text(matrix.filter_field).trim();
  const fallbackColumn = columns[0];
  const selectedColumn =
    configuredField === ""
      ? fallbackColumn
      : columns.find((column) => text(column.key) === configuredField) ||
        fallbackColumn;
  const selectedLabel = text(selectedColumn?.label).trim();
  return {
    field: text(selectedColumn?.key),
    placeholder:
      configuredPlaceholder !== ""
        ? configuredPlaceholder
        : selectedLabel !== ""
        ? `filter ${selectedLabel.toLowerCase()}`
        : "filter rows",
  };
}

function rowFilterSearchText(rowDef, layout, filterField) {
  if (layout === "keyvalue") {
    return text(rowDef.filter_search || rowDef.label || rowDef.field);
  }
  const cells =
    rowDef && typeof rowDef.cells === "object" && rowDef.cells != null
      ? rowDef.cells
      : {};
  const values =
    rowDef && typeof rowDef.values === "object" && rowDef.values != null
      ? rowDef.values
      : {};
  if (filterField !== "") {
    if (Object.prototype.hasOwnProperty.call(cells, filterField)) {
      return text(cells[filterField]);
    }
    if (Object.prototype.hasOwnProperty.call(values, filterField)) {
      return text(values[filterField]);
    }
  }
  return text(rowDef.filter_search || rowDef.search);
}

function enforceGroupMembershipDependencies(row) {
  const memberInput = row.querySelector('input[data-field="member"]');
  const approvedInput = row.querySelector('input[data-field="approved"]');
  const piInput = row.querySelector('input[data-field="pi"]');
  const emailStatusInput = row.querySelector(
    'select[data-field="email_status"]',
  );

  if (!(memberInput instanceof HTMLInputElement)) {
    return;
  }
  if (!(approvedInput instanceof HTMLInputElement)) {
    return;
  }

  const memberEditable = memberInput.dataset.baseDisabled !== "1";
  const approvedEditable = approvedInput.dataset.baseDisabled !== "1";
  const hasPiInput = piInput instanceof HTMLInputElement;
  const piEditable = hasPiInput ? piInput.dataset.baseDisabled !== "1" : false;
  const hasEmailStatusInput = emailStatusInput instanceof HTMLSelectElement;
  const emailStatusEditable = hasEmailStatusInput
    ? emailStatusInput.dataset.baseDisabled !== "1"
    : false;

  memberInput.disabled = !memberEditable;

  if (!memberInput.checked) {
    approvedInput.checked = false;
    if (hasEmailStatusInput) {
      emailStatusInput.value = "none";
    }
    if (hasPiInput) {
      piInput.checked = false;
    }
  }
  approvedInput.disabled = !approvedEditable || !memberInput.checked;
  if (hasEmailStatusInput) {
    if (approvedInput.checked) {
      emailStatusInput.value = "none";
    }
    emailStatusInput.disabled =
      !emailStatusEditable || !memberInput.checked || approvedInput.checked;
  }

  if (!hasPiInput) {
    return;
  }

  if (!approvedInput.checked && piInput.checked) {
    piInput.checked = false;
  }
  piInput.disabled =
    !piEditable || !memberInput.checked || !approvedInput.checked;
}

function readControlValue(control) {
  if (control instanceof HTMLInputElement && control.type === "checkbox") {
    return control.checked;
  }
  return text(control.value);
}

function readOriginalControlValue(control) {
  if (control instanceof HTMLInputElement && control.type === "checkbox") {
    return control.dataset.original === "1";
  }
  return text(control.dataset.original);
}

function controlChanged(control) {
  if (control instanceof HTMLInputElement && control.type === "checkbox") {
    const original = control.dataset.original === "1";
    return control.checked !== original;
  }
  return text(control.value) !== text(control.dataset.original);
}

function isFieldControl(control) {
  return (
    control instanceof HTMLInputElement ||
    control instanceof HTMLSelectElement ||
    control instanceof HTMLTextAreaElement
  );
}

function collectMatrixOperations(block) {
  const rows = block.querySelectorAll("tbody tr");
  const operations = [];

  rows.forEach((row) => {
    const operationRaw = row.dataset.operation || "";
    if (operationRaw === "") {
      return;
    }
    let baseOperation = {};
    try {
      baseOperation = JSON.parse(operationRaw);
    } catch (_error) {
      return;
    }
    if (!baseOperation || typeof baseOperation !== "object") {
      return;
    }
    if (!text(baseOperation.kind)) {
      return;
    }

    const operation = { ...baseOperation };
    let changed = false;
    row.querySelectorAll("[data-field]").forEach((control) => {
      if (!isFieldControl(control)) {
        return;
      }
      const field = text(control.dataset.field);
      if (field === "") {
        return;
      }
      operation[field] = readControlValue(control);
      const expectedField =
        text(operation.kind) === "group.pi.set" && field === "user"
          ? "expected_current_pi"
          : `expected_${field}`;
      operation[expectedField] = readOriginalControlValue(control);
      if (controlChanged(control)) {
        changed = true;
      }
    });

    if (changed) {
      operations.push(operation);
    }
  });

  return operations;
}

function countMatrixChanges(block) {
  const rows = block.querySelectorAll("tbody tr");
  let changedRows = 0;
  rows.forEach((row) => {
    let changed = false;
    row.querySelectorAll("[data-field]").forEach((control) => {
      if (!isFieldControl(control)) {
        return;
      }
      if (controlChanged(control)) {
        changed = true;
      }
    });
    if (changed) {
      changedRows += 1;
    }
  });
  return changedRows;
}

function renderMatrices(container, matrices, onApply, onQuickAdd, notifier) {
  container.replaceChildren();

  if (!Array.isArray(matrices) || matrices.length === 0) {
    const none = document.createElement("p");
    none.className = "none";
    none.textContent = "No editable RBAC state for this selection.";
    container.append(none);
    return;
  }

  const matrixBlocks = document.createDocumentFragment();
  matrices.forEach((matrix) => {
    const block = document.createElement("article");
    block.className = "rbac-matrix";
    block.dataset.matrixId = text(matrix.id);
    block.dataset.behavior = text(matrix.behavior || "");
    if (matrix.compact === true) {
      block.classList.add("rbac-matrix-compact");
    }

    const heading = document.createElement("h3");
    heading.textContent = text(matrix.title || "updates");
    block.append(heading);

    const descriptionText = text(matrix.description);
    if (descriptionText !== "") {
      const description = document.createElement("p");
      description.className = "rbac-matrix-description";
      description.textContent = descriptionText;
      block.append(description);
    }

    const rows = Array.isArray(matrix.rows) ? matrix.rows : [];
    const layout = text(matrix.layout || "");
    const filterSettings = matrixFilterSettings(matrix, layout);
    if (rows.length === 0) {
      const empty = document.createElement("p");
      empty.className = "none";
      empty.textContent = text(matrix.empty || "No rows.");
      block.append(empty);
      matrixBlocks.append(block);
      return;
    }

    const toolbar = document.createElement("div");
    toolbar.className = "rbac-matrix-toolbar";

    const showFilter = matrix.filter !== false;
    let search = null;
    const resultCount = document.createElement("span");
    let moreButtonWrap = null;
    let moreButton = null;
    let matrixVisibleLimit = MATRIX_VISIBLE_ROW_LIMIT;
    let matrixFilterText = "";
    resultCount.className = "rbac-matrix-filter-count";
    if (showFilter) {
      search = document.createElement("input");
      search.type = "search";
      search.placeholder = filterSettings.placeholder;
      search.setAttribute("aria-label", `${text(matrix.title)} row filter`);
      search.className = "rbac-matrix-filter-input";
      toolbar.append(search);
      toolbar.append(resultCount);
      moreButtonWrap = document.createElement("div");
      moreButtonWrap.className = "admin-show-more-wrap";
      moreButtonWrap.hidden = true;
      moreButton = document.createElement("button");
      moreButton.type = "button";
      moreButton.className = "rbac-matrix-show-more admin-show-more-button";
      moreButton.textContent = "show more";
      moreButton.hidden = true;
      moreButtonWrap.append(moreButton);
    }

    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "rbac-matrix-apply";
    apply.textContent = text(matrix.apply_label || "apply updates");
    const quickAdd = matrix.quick_add;
    if (quickAdd && typeof quickAdd === "object") {
      const quickAddButton = document.createElement("button");
      quickAddButton.type = "button";
      quickAddButton.className = "rbac-matrix-quick-add";
      quickAddButton.textContent = text(quickAdd.label || "+ add");
      quickAddButton.addEventListener("click", () =>
        onQuickAdd(matrix, quickAdd),
      );
      toolbar.append(quickAddButton);
    }
    toolbar.append(apply);
    block.append(toolbar);

    const refreshApplyState = () => {
      const changedRows = countMatrixChanges(block);
      apply.disabled = changedRows === 0;
      const suffix = changedRows === 1 ? "row changed" : "rows changed";
      apply.textContent =
        changedRows === 0
          ? text(matrix.apply_label || "apply updates")
          : `${text(
              matrix.apply_label || "apply updates",
            )} (${changedRows} ${suffix})`;
    };

    const table = document.createElement("table");
    table.className = "rbac-matrix-table";
    const tbody = document.createElement("tbody");
    const isGroupMembership = block.dataset.behavior === "group-membership";

    const initializeRowState = (row) => {
      if (isGroupMembership) {
        enforceGroupMembershipDependencies(row);
      }
    };

    const updateFromControlEvent = (target) => {
      if (!isFieldControl(target)) {
        return;
      }
      if (text(target.dataset.field) === "") {
        return;
      }
      const row = target.closest("tr");
      if (!(row instanceof HTMLTableRowElement)) {
        return;
      }
      if (isGroupMembership) {
        enforceGroupMembershipDependencies(row);
      }
      refreshApplyState();
    };

    tbody.addEventListener("change", (event) => {
      updateFromControlEvent(event.target);
    });
    tbody.addEventListener("input", (event) => {
      const target = event.target;
      if (
        !(
          (target instanceof HTMLInputElement && target.type !== "checkbox") ||
          target instanceof HTMLTextAreaElement
        )
      ) {
        return;
      }
      updateFromControlEvent(target);
    });

    if (layout === "keyvalue") {
      block.classList.add("rbac-matrix-keyvalue");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      const nameTh = document.createElement("th");
      nameTh.textContent = "setting";
      const valueTh = document.createElement("th");
      valueTh.textContent = "value";
      headRow.append(nameTh, valueTh);
      thead.append(headRow);
      table.append(thead);

      const rowFragment = document.createDocumentFragment();
      rows.forEach((rowDef) => {
        const row = document.createElement("tr");
        row.dataset.search = rowFilterSearchText(
          rowDef,
          layout,
          filterSettings.field,
        );
        row.dataset.operation = JSON.stringify(rowDef.operation || {});

        const labelCell = document.createElement("td");
        labelCell.dataset.kind = "text";
        labelCell.textContent = text(rowDef.label || rowDef.field || "item");

        const valueCell = document.createElement("td");
        const rowKind = text(rowDef.kind || "text");
        valueCell.dataset.kind = rowKind;
        const field = text(rowDef.field || "");
        const editable = rowDef.editable !== false;

        if (rowKind === "checkbox") {
          const input = document.createElement("input");
          input.type = "checkbox";
          const checked = Boolean(rowDef.value);
          input.checked = checked;
          input.dataset.field = field;
          input.dataset.original = checked ? "1" : "0";
          input.dataset.baseDisabled = editable ? "0" : "1";
          input.disabled = !editable;
          valueCell.append(input);
        } else if (rowKind === "input") {
          const input = document.createElement("input");
          const value = text(rowDef.value);
          input.type = text(rowDef.input_type || "text");
          if (Number(rowDef.max_length) > 0) {
            input.maxLength = Number(rowDef.max_length);
          }
          if (rowDef.placeholder != null) {
            input.placeholder = text(rowDef.placeholder);
          }
          input.value = value;
          input.dataset.field = field;
          input.dataset.original = value;
          input.dataset.baseDisabled = editable ? "0" : "1";
          input.disabled = !editable;
          valueCell.append(input);
        } else if (rowKind === "select") {
          const select = document.createElement("select");
          const value = text(rowDef.value);
          const options = Array.isArray(rowDef.options) ? rowDef.options : [];
          let foundSelected = false;
          options.forEach((optionDef) => {
            const option = document.createElement("option");
            option.value = text(optionDef.value);
            const meta = text(optionDef.meta);
            option.textContent =
              meta === ""
                ? text(optionDef.label ?? optionDef.value)
                : `${text(optionDef.label ?? optionDef.value)} - ${meta}`;
            if (option.value === value) {
              option.selected = true;
              foundSelected = true;
            }
            select.append(option);
          });
          if (value !== "" && !foundSelected) {
            const fallback = document.createElement("option");
            fallback.value = value;
            fallback.textContent = value;
            fallback.selected = true;
            select.append(fallback);
          }
          select.dataset.field = field;
          select.dataset.original = value;
          select.dataset.baseDisabled = editable ? "0" : "1";
          select.disabled = !editable;
          valueCell.append(select);
        } else {
          valueCell.textContent = text(rowDef.value);
        }

        row.append(labelCell, valueCell);
        initializeRowState(row);
        rowFragment.append(row);
      });
      tbody.append(rowFragment);
    } else {
      const columns = Array.isArray(matrix.columns) ? matrix.columns : [];
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      columns.forEach((column) => {
        const th = document.createElement("th");
        th.textContent = text(column.label);
        headRow.append(th);
      });
      thead.append(headRow);
      table.append(thead);

      const rowFragment = document.createDocumentFragment();
      rows.forEach((rowDef) => {
        const row = document.createElement("tr");
        row.dataset.search = rowFilterSearchText(
          rowDef,
          layout,
          filterSettings.field,
        );
        row.dataset.operation = JSON.stringify(rowDef.operation || {});

        columns.forEach((column) => {
          const key = text(column.key);
          const kind = text(column.kind || "text");
          const td = document.createElement("td");
          td.dataset.kind = kind;

          if (kind === "checkbox") {
            const input = document.createElement("input");
            input.type = "checkbox";
            const values = rowDef.values || {};
            const editable = rowDef.editable || {};
            const checked = Boolean(values[key]);
            input.checked = checked;
            input.dataset.field = key;
            input.dataset.original = checked ? "1" : "0";
            const disabled = editable[key] === false;
            input.dataset.baseDisabled = disabled ? "1" : "0";
            input.disabled = disabled;
            td.append(input);
          } else if (kind === "input") {
            const input = document.createElement("input");
            const values = rowDef.values || {};
            const editable = rowDef.editable || {};
            const value = text(values[key]);
            input.type = text(column.input_type || "text");
            if (Number(column.max_length) > 0) {
              input.maxLength = Number(column.max_length);
            }
            if (column.placeholder != null) {
              input.placeholder = text(column.placeholder);
            }
            input.value = value;
            input.dataset.field = key;
            input.dataset.original = value;
            const disabled = editable[key] === false;
            input.dataset.baseDisabled = disabled ? "1" : "0";
            input.disabled = disabled;
            td.append(input);
          } else if (kind === "select") {
            const select = document.createElement("select");
            const values = rowDef.values || {};
            const editable = rowDef.editable || {};
            const value = text(values[key]);
            const options = Array.isArray(column.options) ? column.options : [];
            let foundSelected = false;
            options.forEach((optionDef) => {
              const option = document.createElement("option");
              option.value = text(optionDef.value);
              option.textContent = text(optionDef.label ?? optionDef.value);
              if (option.value === value) {
                option.selected = true;
                foundSelected = true;
              }
              select.append(option);
            });
            if (value !== "" && !foundSelected) {
              const fallback = document.createElement("option");
              fallback.value = value;
              fallback.textContent = value;
              fallback.selected = true;
              select.append(fallback);
            }
            select.dataset.field = key;
            select.dataset.original = value;
            const disabled = editable[key] === false;
            select.dataset.baseDisabled = disabled ? "1" : "0";
            select.disabled = disabled;
            td.append(select);
          } else {
            const cells = rowDef.cells || {};
            td.textContent = text(cells[key]);
          }
          row.append(td);
        });

        initializeRowState(row);
        rowFragment.append(row);
      });
      tbody.append(rowFragment);
    }

    table.append(tbody);
    block.append(table);
    if (moreButtonWrap instanceof HTMLDivElement) {
      block.append(moreButtonWrap);
    }

    const moreCount = Number(matrix.more || 0);
    if (moreCount > 0) {
      const more = document.createElement("p");
      more.className = "rbac-matrix-note-more";
      more.textContent = `Showing first ${rows.length} rows. ${moreCount} additional rows are available.`;
      block.append(more);
    }

    const refreshFilter = () => {
      const query =
        showFilter && search instanceof HTMLInputElement ? search.value : "";
      if (query !== matrixFilterText) {
        matrixVisibleLimit = MATRIX_VISIBLE_ROW_LIMIT;
        matrixFilterText = query;
      }
      const filterState = filterMatrixRows(tbody, query, matrixVisibleLimit);
      if (search instanceof HTMLInputElement) {
        search.classList.remove("rbac-filter-loading");
      }

      if (!showFilter) {
        resultCount.textContent = "";
        if (moreButton instanceof HTMLButtonElement) {
          if (moreButtonWrap instanceof HTMLDivElement) {
            moreButtonWrap.hidden = true;
          }
          moreButton.hidden = true;
          moreButton.textContent = "show more";
        }
        return;
      }

      if (filterState.matchingCount > filterState.visibleCount) {
        const remainingUntilMax = Math.max(
          0,
          MATRIX_VISIBLE_ROW_MAX_LIMIT - matrixVisibleLimit,
        );
        const canShowMore = remainingUntilMax > 0;
        resultCount.textContent = `${filterState.visibleCount}/${
          filterState.matchingCount
        } shown (${filterState.totalCount} total${
          canShowMore ? "" : `, max ${MATRIX_VISIBLE_ROW_MAX_LIMIT}`
        })`;
        if (moreButton instanceof HTMLButtonElement) {
          if (moreButtonWrap instanceof HTMLDivElement) {
            moreButtonWrap.hidden = !canShowMore;
          }
          moreButton.hidden = !canShowMore;
          if (canShowMore) {
            const nextChunk = Math.min(
              MATRIX_VISIBLE_ROW_INCREMENT,
              filterState.matchingCount - filterState.visibleCount,
              remainingUntilMax,
            );
            moreButton.textContent = `show ${nextChunk} more`;
          } else {
            moreButton.textContent = "show more";
          }
        }
        return;
      }

      resultCount.textContent = `${filterState.matchingCount}/${filterState.totalCount} matching`;
      if (moreButton instanceof HTMLButtonElement) {
        if (moreButtonWrap instanceof HTMLDivElement) {
          moreButtonWrap.hidden = true;
        }
        moreButton.hidden = true;
        moreButton.textContent = "show more";
      }
    };

    const debouncedRefreshFilter = debounce(refreshFilter, FILTER_DEBOUNCE_MS);
    if (search instanceof HTMLInputElement) {
      search.addEventListener("input", () => {
        search.classList.add("rbac-filter-loading");
        debouncedRefreshFilter();
      });
    }
    if (
      moreButton instanceof HTMLButtonElement &&
      search instanceof HTMLInputElement
    ) {
      moreButton.addEventListener("click", () => {
        matrixVisibleLimit = Math.min(
          MATRIX_VISIBLE_ROW_MAX_LIMIT,
          matrixVisibleLimit + MATRIX_VISIBLE_ROW_INCREMENT,
        );
        search.classList.add("rbac-filter-loading");
        refreshFilter();
      });
    }
    refreshFilter();

    refreshApplyState();

    apply.addEventListener("click", async () => {
      const operations = collectMatrixOperations(block);
      if (operations.length === 0) {
        notifier.notify("No RBAC changes to apply in this table.", "info");
        return;
      }

      await onApply(matrix, operations);
    });

    matrixBlocks.append(block);
  });
  container.append(matrixBlocks);
}

function initRbacExplorer(root) {
  const endpoint = root.dataset.endpoint;
  const mutationEndpoint = root.dataset.mutationEndpoint || "";
  const auditEndpoint = root.dataset.auditEndpoint || "";
  const initialScope = root.dataset.initialScope || "group";
  const initialEntity = root.dataset.initialEntity || "";
  const initialActive = root.dataset.initialActive || "0";
  const initialCreate = text(root.dataset.initialCreate || "")
    .trim()
    .toLowerCase();
  const controlsForm = root.querySelector(".rbac-controls");
  const csrfTokenInput = root.querySelector("#rbac-csrf-token");
  const scopeSelect = root.querySelector("#rbac-scope");
  const includeInactiveToggle = root.querySelector("#rbac-include-inactive");
  const addGroupButton = root.querySelector("#rbac-add-group");
  const addDeviceButton = root.querySelector("#rbac-add-device");
  const entitySearch = root.querySelector("#rbac-entity-search");
  const entityInput = root.querySelector("#rbac-entity");
  const entityList = root.querySelector("#rbac-entity-list");
  const entityHint = root.querySelector("#rbac-entity-hint");
  const status = root.querySelector("#rbac-status");
  const sourceTitle = root.querySelector("#rbac-sources-title");
  const sources = root.querySelector("#rbac-sources");
  const focus = root.querySelector("#rbac-focus");
  const targetTitle = root.querySelector("#rbac-targets-title");
  const targets = root.querySelector("#rbac-targets");
  const matrices = root.querySelector("#rbac-matrices");
  const auditNote = root.querySelector("#rbac-audit-note");
  const auditList = root.querySelector("#rbac-audit-list");
  const auditShowMoreWrap = root.querySelector("#rbac-audit-show-more-wrap");
  const auditShowMoreButton = root.querySelector("#rbac-audit-show-more");
  const modal = document.querySelector("#rbac-modal");
  const modalTitle = document.querySelector("#rbac-modal-title");
  const modalForm = document.querySelector("#rbac-modal-form");
  const modalFields = document.querySelector("#rbac-modal-fields");
  const modalError = document.querySelector("#rbac-modal-error");
  const modalSubmit = document.querySelector("#rbac-modal-submit");
  const modalCloseNodes = document.querySelectorAll("[data-rbac-modal-close]");

  if (
    !endpoint ||
    !controlsForm ||
    !scopeSelect ||
    !(includeInactiveToggle instanceof HTMLInputElement) ||
    !entitySearch ||
    !entityInput ||
    !entityList ||
    !entityHint ||
    !status ||
    !sourceTitle ||
    !sources ||
    !focus ||
    !targetTitle ||
    !targets ||
    !matrices ||
    !(addGroupButton instanceof HTMLButtonElement) ||
    !(addDeviceButton instanceof HTMLButtonElement) ||
    !(modal instanceof HTMLElement) ||
    !(modalTitle instanceof HTMLElement) ||
    !(modalForm instanceof HTMLFormElement) ||
    !(modalFields instanceof HTMLElement) ||
    !(modalError instanceof HTMLElement) ||
    !(modalSubmit instanceof HTMLButtonElement)
  ) {
    return;
  }

  let requestCounter = 0;
  let auditRequestCounter = 0;
  let loadedEntities = [];
  let visibleEntities = [];
  let entitySuggestionLimit = ENTITY_SUGGESTION_LIMIT;
  let activeEntityIndex = -1;
  let suggestionsOpen = false;
  let currentScope = initialScope;
  let currentEntity = initialEntity;
  let includeInactive = text(initialActive).trim() === "1";
  let auditVisibleLimit = RBAC_SHOW_MORE_DEFAULT_LIMIT;
  let initialCreateHandled = false;
  const canMutate = Boolean(mutationEndpoint && csrfTokenInput);
  const canLoadAudit = Boolean(auditEndpoint && auditNote && auditList);
  const notifier = getAppNotifier({ fallbackStatusNode: status });
  includeInactiveToggle.checked = includeInactive;

  const selectedEntity = () =>
    loadedEntities.find((entity) => entity.id === currentEntity) || null;

  const closeEntitySuggestions = () => {
    suggestionsOpen = false;
    activeEntityIndex = -1;
    visibleEntities = [];
    entitySuggestionLimit = ENTITY_SUGGESTION_LIMIT;
    entitySearch.classList.remove("rbac-filter-loading");
    renderEntitySuggestions(entityList, entitySearch, [], -1, currentEntity);
  };

  const openEntitySuggestions = () => {
    suggestionsOpen = true;
    refreshEntityOptions({ resetLimit: true });
  };

  const refreshEntityOptions = ({
    preserveActive = false,
    resetLimit = false,
  } = {}) => {
    if (resetLimit) {
      entitySuggestionLimit = ENTITY_SUGGESTION_LIMIT;
    }

    const query = entitySearch.value;
    const queryText = text(query).trim();
    const ranked = rankEntities(query, loadedEntities);
    const selected = selectedEntity();

    let renderedEntities = ranked;
    let selectionPinned = false;
    if (
      selected &&
      !renderedEntities.some((entity) => entity.id === selected.id)
    ) {
      renderedEntities = [selected, ...renderedEntities];
      selectionPinned = true;
    }

    const limit = Math.max(0, Math.floor(Number(entitySuggestionLimit) || 0));
    const cappedLimit = limit > 0 ? limit : renderedEntities.length;
    visibleEntities = suggestionsOpen
      ? renderedEntities.slice(0, cappedLimit)
      : [];
    const showMoreSuggestions =
      suggestionsOpen && renderedEntities.length > visibleEntities.length;
    if (!preserveActive) {
      if (visibleEntities.length === 0) {
        activeEntityIndex = -1;
      } else if (queryText !== "") {
        activeEntityIndex =
          selectionPinned && visibleEntities.length > 1 ? 1 : 0;
      } else {
        const selectedIndex = visibleEntities.findIndex(
          (entity) => entity.id === currentEntity,
        );
        activeEntityIndex = selectedIndex >= 0 ? selectedIndex : 0;
      }
    } else if (activeEntityIndex >= visibleEntities.length) {
      activeEntityIndex = visibleEntities.length - 1;
    }

    renderEntitySuggestions(
      entityList,
      entitySearch,
      visibleEntities,
      activeEntityIndex,
      currentEntity,
      showMoreSuggestions,
    );
    entityInput.value = currentEntity;

    const totalCount = loadedEntities.length;
    const matchedCount = ranked.length;
    const shownCount = visibleEntities.length;

    if (totalCount === 0) {
      entityHint.textContent = "No entities available in this scope.";
      entitySearch.classList.remove("rbac-filter-loading");
      return;
    }

    if (queryText === "") {
      if (showMoreSuggestions) {
        entityHint.textContent = `Showing ${shownCount} of ${totalCount} matches (show more available).`;
      } else if (shownCount > 0 && shownCount < totalCount) {
        entityHint.textContent = `Showing ${shownCount} of ${totalCount} entities.`;
      } else {
        entityHint.textContent = `Showing ${totalCount} entities.`;
      }
      entitySearch.classList.remove("rbac-filter-loading");
      return;
    }

    if (matchedCount === 0) {
      if (selectionPinned) {
        entityHint.textContent = `No matches for "${queryText}" (current selection kept).`;
      } else {
        entityHint.textContent = `No matches for "${queryText}".`;
      }
      entitySearch.classList.remove("rbac-filter-loading");
      return;
    }

    if (selectionPinned) {
      if (showMoreSuggestions) {
        entityHint.textContent = `${matchedCount} matches for "${queryText}" (current selection kept, showing ${shownCount}).`;
      } else {
        entityHint.textContent = `${matchedCount} matches for "${queryText}" (current selection kept).`;
      }
      entitySearch.classList.remove("rbac-filter-loading");
      return;
    }

    if (shownCount > 0 && matchedCount > shownCount) {
      entityHint.textContent = `${matchedCount} matches for "${queryText}" (showing top ${shownCount}).`;
      entitySearch.classList.remove("rbac-filter-loading");
      return;
    }

    entityHint.textContent = `${matchedCount} matches for "${queryText}" (of ${totalCount}).`;

    entitySearch.classList.remove("rbac-filter-loading");
  };

  const debouncedRefreshEntityOptions = debounce(
    () => refreshEntityOptions({ preserveActive: true }),
    FILTER_DEBOUNCE_MS,
  );

  const findEntityByQuery = () => {
    const queryText = text(entitySearch.value).trim();
    if (queryText === "") {
      return selectedEntity() || loadedEntities[0] || null;
    }

    const normalizedQuery = normalizeFuzzy(queryText);
    const exact = loadedEntities.find(
      (entity) =>
        normalizeFuzzy(entity.id) === normalizedQuery ||
        normalizeFuzzy(entity.label) === normalizedQuery,
    );
    if (exact) {
      return exact;
    }

    const ranked = rankEntities(queryText, loadedEntities);
    return ranked.length > 0 ? ranked[0] : null;
  };

  const syncAuditShowMore = (payload) => {
    if (
      !(auditShowMoreWrap instanceof HTMLElement) ||
      !(auditShowMoreButton instanceof HTMLButtonElement)
    ) {
      return;
    }
    const events = Array.isArray(payload?.events) ? payload.events : [];
    const hasMore =
      events.length === auditVisibleLimit &&
      auditVisibleLimit < RBAC_SHOW_MORE_MAX_LIMIT;
    auditShowMoreWrap.hidden = !hasMore;
    auditShowMoreButton.hidden = !hasMore;
    auditShowMoreButton.textContent = "show more";
  };

  const loadAudit = async (scope, entity, { preserveLimit = false } = {}) => {
    if (!canLoadAudit) {
      return;
    }
    if (!preserveLimit) {
      auditVisibleLimit = RBAC_SHOW_MORE_DEFAULT_LIMIT;
    }

    auditRequestCounter += 1;
    const requestId = auditRequestCounter;

    const params = new URLSearchParams({
      scope,
      limit: String(auditVisibleLimit),
    });
    if (entity) {
      params.set("entity", entity);
    }

    let payload = null;
    try {
      const response = await fetch(`${auditEndpoint}?${params.toString()}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      payload = await response.json();
    } catch (_error) {
      if (requestId !== auditRequestCounter) {
        return;
      }
      if (auditNote && auditList) {
        auditList.replaceChildren();
        auditNote.textContent = "Failed to load RBAC audit events.";
        syncAuditShowMore({ events: [] });
      }
      return;
    }

    if (requestId !== auditRequestCounter) {
      return;
    }
    if (auditNote && auditList) {
      renderAuditEvents(auditList, auditNote, payload, scope, entity);
      syncAuditShowMore(payload);
    }
  };

  let modalConfig = null;

  const closeModal = () => {
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    modalError.textContent = "";
    modalFields.replaceChildren();
    modalForm.reset();
    modalConfig = null;
  };

  const notifyModalError = (message, control = null) => {
    modalError.textContent = "";
    notifier.notify(text(message), "error", { sticky: true });
    if (control instanceof HTMLElement) {
      control.focus();
    }
  };

  const openModal = (config) => {
    modalConfig = config;
    modalTitle.textContent = text(config.title || "RBAC update");
    modalSubmit.textContent = text(config.submitLabel || "apply");
    modalError.textContent = "";
    modalFields.replaceChildren();

    const fields = Array.isArray(config.fields) ? config.fields : [];
    fields.forEach((field, index) => {
      const fieldType = text(field.type || "text");
      const fieldName = text(field.name);
      if (fieldName === "") {
        return;
      }
      const fieldId = `rbac-modal-${fieldName}-${index}`;
      const row = document.createElement("div");
      row.className = "rbac-modal-row";
      let control = null;

      if (fieldType === "checkbox") {
        const checkboxLabel = document.createElement("label");
        checkboxLabel.setAttribute("for", fieldId);
        control = document.createElement("input");
        control.type = "checkbox";
        control.id = fieldId;
        control.name = fieldName;
        control.checked = Boolean(field.default);
        checkboxLabel.append(
          control,
          document.createTextNode(` ${text(field.label)}`),
        );
        row.append(checkboxLabel);
      } else {
        const label = document.createElement("label");
        label.setAttribute("for", fieldId);
        label.textContent = text(field.label || fieldName);

        if (fieldType === "select") {
          control = document.createElement("select");
          control.id = fieldId;
          control.name = fieldName;
          const required = field.required === true;
          if (required) {
            const empty = document.createElement("option");
            empty.value = "";
            empty.textContent = "select...";
            control.append(empty);
          }
          const options = Array.isArray(field.options) ? field.options : [];
          options.forEach((optionDef) => {
            const option = document.createElement("option");
            option.value = text(optionDef.value);
            const meta = text(optionDef.meta);
            option.textContent =
              meta === ""
                ? text(optionDef.label ?? optionDef.value)
                : `${text(optionDef.label ?? optionDef.value)} - ${meta}`;
            control.append(option);
          });
          if (field.default != null) {
            control.value = text(field.default);
          }
          if (required) {
            control.required = true;
          }
        } else if (fieldType === "textarea") {
          control = document.createElement("textarea");
          control.id = fieldId;
          control.name = fieldName;
          control.value = text(field.default);
        } else {
          control = document.createElement("input");
          control.id = fieldId;
          control.name = fieldName;
          control.type = fieldType;
          control.value = text(field.default);
          if (Number(field.maxLength) > 0) {
            control.maxLength = Number(field.maxLength);
          }
          if (field.list) {
            control.setAttribute("list", text(field.list));
          }
        }

        if (
          field.required === true &&
          (control instanceof HTMLInputElement ||
            control instanceof HTMLTextAreaElement)
        ) {
          control.required = true;
        }
        if (
          field.placeholder &&
          (control instanceof HTMLInputElement ||
            control instanceof HTMLTextAreaElement)
        ) {
          control.placeholder = text(field.placeholder);
        }
        row.append(label, control);
      }

      modalFields.append(row);
    });

    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    const firstInput = modalFields.querySelector("input, select, textarea");
    if (firstInput instanceof HTMLElement) {
      firstInput.focus();
    }
  };

  const runBatchMutation = async (_matrix, operations, options = {}) => {
    if (!canMutate) {
      notifier.notify(
        "Mutation controls are unavailable in this RBAC view.",
        "error",
      );
      return false;
    }
    const submitScope = text(
      options.scope || currentScope || scopeSelect.value,
    );
    const submitEntity = text(options.entity || currentEntity || "");
    if (!options.allowNoEntity && submitEntity === "") {
      notifier.notify(
        "Select an entity before applying RBAC changes.",
        "error",
      );
      return false;
    }

    const formBody = new URLSearchParams();
    formBody.set("csrf_token", text(csrfTokenInput.value));
    formBody.set("scope", submitScope);
    formBody.set("entity", submitEntity === "" ? "__rbac__" : submitEntity);
    formBody.set("operations", JSON.stringify(operations));

    setStatus(status, "Applying RBAC updates atomically...", "info");

    let payload = null;
    let responseStatus = 0;
    try {
      const response = await fetch(mutationEndpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        },
        body: formBody.toString(),
      });
      responseStatus = response.status;
      payload = await response.json();
      if (!response.ok || !payload?.ok) {
        throw new Error(
          text(payload?.message || `Request failed (${response.status})`),
        );
      }
    } catch (error) {
      const firstIssue = Array.isArray(payload?.results)
        ? payload.results.find(
            (row) =>
              row.status === "invalid" ||
              row.status === "rolled_back" ||
              row.status === "conflict",
          )
        : null;
      const details = firstIssue ? ` ${text(firstIssue.message)}` : "";
      notifier.notify(
        `RBAC update failed (${responseStatus || "error"}): ${text(
          error.message,
        )}${details}`,
        "error",
      );
      setStatus(status, "RBAC updates were not applied.", "info");
      return false;
    }

    notifier.notify(
      text(payload.message || "RBAC updates applied."),
      "success",
    );
    const resultRows = Array.isArray(payload?.results) ? payload.results : [];
    if (resultRows.length > 0) {
      const seen = new Set();
      const maxOperationMessages = 6;
      const operationMessages = [];

      for (const row of resultRows) {
        const rawMessage = text(row?.message);
        if (rawMessage === "") {
          continue;
        }
        const status = text(row?.status || "").toLowerCase();
        let level = "info";
        const message = rawMessage.trim();
        if (
          status === "applied" &&
          message.toLowerCase().includes("resent request email")
        ) {
          level = "success";
          if (message.toLowerCase().includes("failed")) {
            level = "warning";
          }
        } else if (status === "applied") {
          level = "success";
        } else if (status === "invalid") {
          level = "error";
        } else if (status === "unchanged") {
          level = "info";
        } else if (status === "rolled_back" || status === "conflict") {
          level = "error";
        }
        const key = `${status}:${message}`;
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        operationMessages.push({
          level,
          message,
        });
      }

      if (operationMessages.length > 0) {
        operationMessages.slice(0, maxOperationMessages).forEach((row) => {
          notifier.notify(row.message, row.level);
        });
        const extra = operationMessages.length - maxOperationMessages;
        if (extra > 0) {
          notifier.notify(`...and ${extra} more RBAC update note(s).`, "info");
        }
      }
    }
    setStatus(status, "Refreshing RBAC relationships...", "info");
    if (options.reloadEntities === true) {
      const refreshScope = text(options.refreshScope || submitScope || "group");
      const refreshEntity = text(options.refreshEntity || "");
      scopeSelect.value = refreshScope;
      await load(refreshScope, refreshEntity, true, "entities");
    } else {
      const refreshScope = text(options.refreshScope || scopeSelect.value);
      const refreshEntity = text(
        options.refreshEntity || currentEntity || submitEntity,
      );
      await load(refreshScope, refreshEntity, true, "detail");
    }
    return true;
  };

  modalCloseNodes.forEach((node) => {
    node.addEventListener("click", () => closeModal());
  });

  modalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!modalConfig) {
      return;
    }
    const fields = Array.isArray(modalConfig.fields) ? modalConfig.fields : [];
    const values = {};
    for (const field of fields) {
      const name = text(field.name);
      if (name === "") {
        continue;
      }
      const control = modalForm.elements.namedItem(name);
      if (
        !(
          control instanceof HTMLInputElement ||
          control instanceof HTMLSelectElement ||
          control instanceof HTMLTextAreaElement
        )
      ) {
        continue;
      }
      const value =
        control instanceof HTMLInputElement && control.type === "checkbox"
          ? control.checked
          : text(control.value).trim();
      if (
        field.required === true &&
        typeof value === "string" &&
        value === ""
      ) {
        notifyModalError(`${text(field.label || name)} is required.`, control);
        return;
      }
      values[name] = value;
    }

    if (typeof modalConfig.toOperations !== "function") {
      notifyModalError("Missing modal submit handler.");
      return;
    }
    const submission = modalConfig.toOperations(values);
    const operations = Array.isArray(submission?.operations)
      ? submission.operations
      : [];
    if (operations.length === 0) {
      notifyModalError("No RBAC changes to apply.");
      return;
    }

    modalSubmit.disabled = true;
    const ok = await runBatchMutation(
      null,
      operations,
      submission.options || {},
    );
    modalSubmit.disabled = false;
    if (ok) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.hidden === false) {
      closeModal();
    }
  });

  const openCreateGroupModal = () => {
    openModal({
      title: "Add Group",
      submitLabel: "create group",
      fields: [
        {
          name: "group",
          label: "group id",
          type: "text",
          required: true,
          maxLength: 10,
        },
        {
          name: "label",
          label: "short label",
          type: "text",
          required: true,
          maxLength: 20,
        },
        {
          name: "description",
          label: "long label",
          type: "text",
          required: true,
          maxLength: 75,
        },
        {
          name: "pi",
          label: "PI user id",
          type: "text",
          required: true,
          maxLength: 20,
        },
        { name: "addr", label: "email", type: "text" },
        { name: "link", label: "link", type: "url" },
        {
          name: "color",
          label: "legend color",
          type: "color",
          required: true,
          default: "#000000",
        },
        {
          name: "inst",
          label: "institute",
          type: "text",
          list: "rbac-institutes-options",
        },
        { name: "active", label: "active", type: "checkbox", default: true },
      ],
      toOperations: (values) => ({
        operations: [
          {
            kind: "group.create",
            group: text(values.group),
            label: text(values.label),
            description: text(values.description),
            pi: text(values.pi),
            addr: text(values.addr),
            link: text(values.link),
            color: text(values.color || "#000000"),
            inst: text(values.inst),
            active: Boolean(values.active),
          },
        ],
        options: {
          scope: "group",
          entity: "__create__",
          allowNoEntity: true,
          reloadEntities: true,
          refreshScope: "group",
          refreshEntity: text(values.group),
        },
      }),
    });
  };

  const openCreateDeviceModal = () => {
    openModal({
      title: "Add Device",
      submitLabel: "create device",
      fields: [
        {
          name: "device",
          label: "device id",
          type: "text",
          required: true,
          maxLength: 5,
        },
        {
          name: "label",
          label: "label",
          type: "text",
          required: true,
          maxLength: 25,
        },
        { name: "description", label: "description", type: "text" },
        { name: "addr", label: "email", type: "text" },
        { name: "tech_addr", label: "tech email", type: "text" },
        { name: "med_addr", label: "medical email", type: "text" },
        { name: "train_addr", label: "training email", type: "text" },
        { name: "active", label: "active", type: "checkbox", default: true },
      ],
      toOperations: (values) => ({
        operations: [
          {
            kind: "device.create",
            device: text(values.device),
            label: text(values.label),
            description: text(values.description),
            addr: text(values.addr),
            tech_addr: text(values.tech_addr),
            med_addr: text(values.med_addr),
            train_addr: text(values.train_addr),
            active: Boolean(values.active),
          },
        ],
        options: {
          scope: "device",
          entity: "__create__",
          allowNoEntity: true,
          reloadEntities: true,
          refreshScope: "device",
          refreshEntity: text(values.device),
        },
      }),
    });
  };

  const openQuickAddModal = (_matrix, quickAdd) => {
    const fields = Array.isArray(quickAdd.fields) ? quickAdd.fields : [];
    const baseOperation =
      quickAdd.operation && typeof quickAdd.operation === "object"
        ? quickAdd.operation
        : {};
    openModal({
      title: text(quickAdd.title || "Add RBAC entry"),
      submitLabel: text(quickAdd.submit_label || "apply"),
      fields,
      toOperations: (values) => ({
        operations: [{ ...baseOperation, ...values }],
        options: {
          scope: text(quickAdd.scope || currentScope),
          entity: text(quickAdd.entity || currentEntity),
        },
      }),
    });
  };

  const maybeOpenInitialCreateModal = () => {
    if (initialCreateHandled) {
      return;
    }
    if (initialCreate !== "group" && initialCreate !== "device") {
      return;
    }
    initialCreateHandled = true;
    if (initialCreate === "group") {
      openCreateGroupModal();
    } else {
      openCreateDeviceModal();
    }
    syncUrl(currentScope, currentEntity, includeInactive);
  };

  const render = (payload, mode = "full") => {
    currentScope = text(payload.scope || currentScope);
    if (typeof payload.include_inactive === "boolean") {
      includeInactive = payload.include_inactive;
      includeInactiveToggle.checked = includeInactive;
    }
    const payloadSelected = text(payload.selected || "");
    if (payloadSelected !== "") {
      currentEntity = payloadSelected;
    }
    if (Array.isArray(payload.entities)) {
      if (payload.entities_included === false) {
        // keep current entity list
      } else if (
        mode === "detail" &&
        payload.entities.length === 0 &&
        loadedEntities.length > 0 &&
        payload.entities_included == null
      ) {
        // backward compatibility
      } else {
        loadedEntities = payload.entities;
      }
    }

    if (Array.isArray(payload.scopes) && payload.scopes.length > 0) {
      renderScopeOptions(scopeSelect, payload.scopes || [], currentScope);
    }

    if (loadedEntities.length === 0) {
      currentEntity = "";
      entityInput.value = "";
    } else if (!loadedEntities.some((entity) => entity.id === currentEntity)) {
      currentEntity = loadedEntities[0].id;
    }

    const selected = selectedEntity();
    if (selected) {
      entitySearch.value = text(selected.label);
      entityInput.value = text(selected.id);
    }

    refreshEntityOptions({ preserveActive: true });

    const detail = payload.detail || {};

    const graph = detail.graph || {};
    sourceTitle.textContent = text(graph.source_title || "source");
    targetTitle.textContent = text(graph.target_title || "target");
    focus.replaceChildren();
    const focusLabel = text(graph.focus?.label || "Nothing selected");
    if (graph.focus?.href) {
      focus.append(makeLink(focusLabel, text(graph.focus.href)));
    } else {
      focus.textContent = focusLabel;
    }
    renderGraphSide(
      sources,
      graph.sources || [],
      "sources",
      Number(graph.source_more || 0),
    );
    renderGraphSide(
      targets,
      graph.targets || [],
      "targets",
      Number(graph.target_more || 0),
    );

    renderMatrices(
      matrices,
      detail.matrices || [],
      runBatchMutation,
      openQuickAddModal,
      notifier,
    );
  };

  const load = async (scope, entity, pushUrl = true, mode = "full") => {
    requestCounter += 1;
    const requestId = requestCounter;
    if (mode === "entities") {
      setStatus(status, "Loading entities...", "info");
    } else {
      setStatus(status, "Loading RBAC relationships...", "info");
    }

    const params = new URLSearchParams({ scope });
    params.set("active", includeInactive ? "1" : "0");
    if (entity) {
      params.set("entity", entity);
    }
    if (mode === "entities") {
      params.set("detail", "0");
      params.set("entities", "1");
    } else if (mode === "detail") {
      params.set("detail", "1");
      params.set("entities", "0");
    }

    let payload = null;
    try {
      const response = await fetch(`${endpoint}?${params.toString()}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }

      payload = await response.json();
    } catch (error) {
      if (requestId !== requestCounter) {
        return;
      }
      setStatus(status, "Failed to load RBAC explorer.", "error");
      notifier.notify(
        `Failed to load RBAC explorer: ${error.message}`,
        "error",
      );
      return;
    }

    if (requestId !== requestCounter) {
      return;
    }

    render(payload, mode);

    if (mode === "entities") {
      const entityCount = Array.isArray(payload.entities)
        ? payload.entities.length
        : 0;
      setStatus(
        status,
        `Loaded ${entityCount} ${text(payload.scope || scope)} entries.`,
        "ok",
      );
      const chosenEntity = text(
        entity || currentEntity || loadedEntities[0]?.id || "",
      );
      if (chosenEntity) {
        currentEntity = chosenEntity;
        entityInput.value = chosenEntity;
        await load(scope, chosenEntity, false, "detail");
      } else if (canLoadAudit && auditNote && auditList) {
        auditVisibleLimit = RBAC_SHOW_MORE_DEFAULT_LIMIT;
        renderAuditEvents(
          auditList,
          auditNote,
          { events: [], limit: 0 },
          text(payload.scope || scope),
          "",
        );
        syncAuditShowMore({ events: [] });
      }
    } else {
      await loadAudit(
        text(payload.scope || scope),
        text(payload.selected || currentEntity || entity),
      );
      setStatus(status, "Relationships loaded.", "ok");
    }

    if (pushUrl) {
      if (mode === "entities") {
        syncUrl(
          text(payload.scope || scope),
          text(currentEntity || entity),
          includeInactive,
        );
      } else {
        syncUrl(
          text(payload.scope || scope),
          text(payload.selected || entity),
          includeInactive,
        );
      }
    }
  };

  const chooseEntityAndLoad = async (entity, pushUrl = true) => {
    if (!entity) {
      return;
    }
    currentEntity = text(entity.id);
    entityInput.value = text(entity.id);
    entitySearch.value = text(entity.label);
    closeEntitySuggestions();
    await load(scopeSelect.value, currentEntity, pushUrl, "detail");
  };

  controlsForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const chosen =
      visibleEntities[activeEntityIndex] ||
      findEntityByQuery() ||
      selectedEntity();
    if (!chosen) {
      return;
    }
    chooseEntityAndLoad(chosen, true);
  });

  scopeSelect.addEventListener("change", () => {
    entitySearch.value = "";
    closeEntitySuggestions();
    currentEntity = "";
    entityInput.value = "";
    load(scopeSelect.value, "", true, "entities");
  });

  includeInactiveToggle.addEventListener("change", () => {
    includeInactive = includeInactiveToggle.checked;
    closeEntitySuggestions();
    load(scopeSelect.value, currentEntity, true, "entities");
  });

  addGroupButton.addEventListener("click", () => {
    openCreateGroupModal();
  });

  addDeviceButton.addEventListener("click", () => {
    openCreateDeviceModal();
  });

  if (
    canLoadAudit &&
    auditShowMoreButton instanceof HTMLButtonElement &&
    auditShowMoreWrap instanceof HTMLElement
  ) {
    auditShowMoreButton.addEventListener("click", async () => {
      if (auditVisibleLimit >= RBAC_SHOW_MORE_MAX_LIMIT) {
        auditShowMoreWrap.hidden = true;
        return;
      }
      auditVisibleLimit = Math.min(
        RBAC_SHOW_MORE_MAX_LIMIT,
        auditVisibleLimit + RBAC_SHOW_MORE_INCREMENT,
      );
      await loadAudit(currentScope, currentEntity, { preserveLimit: true });
    });
  }

  entitySearch.addEventListener("focus", () => {
    openEntitySuggestions();
  });

  entitySearch.addEventListener("input", () => {
    suggestionsOpen = true;
    activeEntityIndex = -1;
    entitySuggestionLimit = ENTITY_SUGGESTION_LIMIT;
    entitySearch.classList.add("rbac-filter-loading");
    debouncedRefreshEntityOptions();
  });

  entitySearch.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!suggestionsOpen) {
        openEntitySuggestions();
      }
      if (visibleEntities.length === 0) {
        return;
      }
      event.preventDefault();
      if (event.key === "ArrowDown") {
        activeEntityIndex = (activeEntityIndex + 1) % visibleEntities.length;
      } else if (activeEntityIndex <= 0) {
        activeEntityIndex = visibleEntities.length - 1;
      } else {
        activeEntityIndex -= 1;
      }
      refreshEntityOptions({ preserveActive: true });
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      const chosen = selectedEntity();
      if (chosen) {
        entitySearch.value = text(chosen.label);
      }
      closeEntitySuggestions();
      return;
    }

    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    const chosen =
      visibleEntities[activeEntityIndex] ||
      findEntityByQuery() ||
      selectedEntity();
    if (!chosen) {
      return;
    }
    chooseEntityAndLoad(chosen, true);
  });

  entitySearch.addEventListener("blur", () => {
    window.setTimeout(() => {
      closeEntitySuggestions();
      const chosen = selectedEntity();
      if (chosen) {
        entitySearch.value = text(chosen.label);
      }
    }, 100);
  });

  entityList.addEventListener("mousedown", (event) => {
    event.preventDefault();
  });

  entityList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const showMoreTarget = target.closest("[data-show-more]");
    if (showMoreTarget instanceof HTMLElement) {
      entitySuggestionLimit += ENTITY_SUGGESTION_INCREMENT;
      entitySearch.classList.add("rbac-filter-loading");
      refreshEntityOptions({ preserveActive: true });
      return;
    }
    const option = target.closest("[data-entity-id]");
    if (!(option instanceof HTMLElement)) {
      return;
    }
    const entityId = text(option.dataset.entityId);
    const chosen = loadedEntities.find((entity) => entity.id === entityId);
    if (!chosen) {
      return;
    }
    chooseEntityAndLoad(chosen, true);
  });

  load(initialScope, initialEntity, false, "entities").then(() => {
    maybeOpenInitialCreateModal();
  });
}

function main() {
  const root = document.querySelector("[data-rbac-explorer]");
  if (root) {
    initRbacExplorer(root);
  }
}

export {
  collectMatrixOperations,
  countMatrixChanges,
  fuzzyScore,
  initRbacExplorer,
  main,
  rankEntities,
  renderAuditEvents,
  renderEntitySuggestions,
  renderMatrices,
  setStatus,
  syncUrl,
};
