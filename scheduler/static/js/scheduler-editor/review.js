import { fmt_editor_diff_details } from "./formatters.js";

const pluralize = (count, noun) => `${count} ${noun}${count == 1 ? "" : "s"}`;

const status_token = (label, state) => {
  const token = document.createElement("span");
  token.className = "review-item-status";
  token.dataset.state = state;
  token.textContent = label;
  return token;
};

const build_review_header = (item, stateLabel, state) => {
  const header = document.createElement("div");
  header.className = "review-item-header";

  const titleGroup = document.createElement("div");
  titleGroup.className = "review-item-title-group";

  const title = document.createElement("p");
  title.className = "review-item-title";
  title.textContent = item.label;
  titleGroup.append(title);

  if (item.summary) {
    const summary = document.createElement("p");
    summary.className = "review-item-summary";
    summary.textContent = item.summary;
    titleGroup.append(summary);
  }

  header.append(titleGroup, status_token(stateLabel, state));
  return header;
};

const build_issue_messages = (item) => {
  if (!Array.isArray(item.errors) || item.errors.length == 0) {
    return null;
  }
  const list = document.createElement("ul");
  list.className = "review-item-errors";
  for (const errorMessage of item.errors) {
    const row = document.createElement("li");
    row.textContent = errorMessage;
    list.append(row);
  }
  return list;
};

function createResolveAction(item, onResolve, labelText, extraBody = null) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "review-item-action";
  button.dataset.reviewCellId = String(item.id);
  button.setAttribute("aria-label", `Open Selection Details for ${item.label}`);
  button.append(build_review_header(item, labelText, "issue"));
  if (extraBody) {
    button.append(extraBody);
  }
  button.addEventListener("click", (evt) => {
    evt.preventDefault();
    onResolve?.(item);
  });
  return button;
}

function createSelectableChange(
  item,
  selectedIds,
  manuallyDeselectedIds,
  syncSelectionState,
) {
  const row = document.createElement("div");
  row.className = "review-item-action review-item-action-selectable";

  const toggle = document.createElement("label");
  toggle.className = "review-item-toggle";

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "review-item-checkbox";
  checkbox.dataset.reviewCellId = String(item.id);
  checkbox.checked = selectedIds.has(String(item.id));

  const copy = document.createElement("div");
  copy.className = "review-item-toggle-copy";
  copy.append(build_review_header(item, "Ready", "ready"));
  copy.append(fmt_editor_diff_details(item.diff));

  toggle.append(checkbox, copy);
  row.append(toggle);

  checkbox.addEventListener("change", () => {
    const key = String(item.id);
    if (checkbox.checked) {
      manuallyDeselectedIds.delete(key);
      selectedIds.add(key);
    } else {
      manuallyDeselectedIds.add(key);
      selectedIds.delete(key);
    }
    syncSelectionState();
  });

  return row;
}

function createBlockedChange(item, onResolve) {
  const body = document.createElement("div");
  body.className = "review-item-body";
  body.append(fmt_editor_diff_details(item.diff));

  if (Array.isArray(item.errors) && item.errors.length > 0) {
    const issueList = build_issue_messages(item);
    if (issueList) {
      body.append(issueList);
    }
  }

  return createResolveAction(item, onResolve, "Resolve first", body);
}

function createIssueItem(item, onResolve) {
  const body = document.createElement("div");
  body.className = "review-item-body";
  const messages = build_issue_messages(item);
  if (messages) {
    body.append(messages);
  }
  return createResolveAction(item, onResolve, "Needs attention", body);
}

function createReviewDialog({
  getChanges = () => [],
  getIssues = () => [],
  onResolve,
  submitText = "Confirm",
  closeText = "Close",
  cancelText = "Keep editing",
  shouldShowNotifications = () => false,
} = {}) {
  const selectedIds = new Set();
  const manuallyDeselectedIds = new Set();
  const content = document.createElement("div");
  const refreshButton = document.createElement("button");
  let confirmButton = null;
  let cancelButton = null;
  let headerActions = null;
  let title = null;
  let notificationsCon = null;
  let selectionStatus = null;
  let changes = [];
  let issues = [];

  refreshButton.type = "button";
  refreshButton.className = "review-dialog-refresh";
  refreshButton.textContent = "Refresh";
  refreshButton.setAttribute("aria-label", "Refresh review");

  const readyChanges = () => changes.filter((change) => !change.blocking);
  const titleText = () =>
    changes.length > 0
      ? "review pending changes"
      : issues.length > 0
      ? "review issues"
      : "no pending changes";
  const selectedChanges = () =>
    readyChanges().filter((change) => selectedIds.has(String(change.id)));
  const hasReadyChanges = () => readyChanges().length > 0;
  const syncSelectedIds = () => {
    const availableIds = new Set(
      readyChanges().map((change) => String(change.id)),
    );
    selectedIds.clear();
    for (const id of availableIds) {
      if (!manuallyDeselectedIds.has(id)) {
        selectedIds.add(id);
      }
    }
  };

  const syncSelectionState = () => {
    if (selectionStatus) {
      if (!hasReadyChanges()) {
        selectionStatus.textContent =
          "Resolve the pending issue rows before confirming changes.";
      } else if (selectedIds.size == 0) {
        selectionStatus.textContent =
          "Select at least one ready change to confirm.";
      } else {
        selectionStatus.textContent = `${pluralize(
          selectedIds.size,
          "ready change",
        )} selected.`;
      }
    }
    if (title) {
      title.innerText = titleText();
    }
    if (cancelButton) {
      cancelButton.hidden = !hasReadyChanges();
      cancelButton.innerText = cancelText;
    }
    if (confirmButton) {
      confirmButton.innerText = hasReadyChanges() ? submitText : closeText;
      confirmButton.disabled = hasReadyChanges() && selectedIds.size == 0;
    }
    if (notificationsCon) {
      notificationsCon.hidden = !(
        hasReadyChanges() &&
        shouldShowNotifications(selectedChanges().map((change) => change.diff))
      );
    }
  };

  const requestResolve = (item) => {
    onResolve?.(item);
  };

  const render = () => {
    content.replaceChildren();
    selectionStatus = null;

    const addSection = (titleText) => {
      const section = document.createElement("section");
      section.className = "review-section";
      const heading = document.createElement("h2");
      heading.textContent = titleText;
      section.append(heading);
      content.append(section);
      return section;
    };

    if (issues.length > 0) {
      const issueSection = addSection(
        issues.length == 1 ? "Active issue" : "Active issues",
      );
      const intro = document.createElement("p");
      intro.textContent =
        "Select an issue row to reopen Selection Details and resolve it.";
      issueSection.append(intro);
      const list = document.createElement("ul");
      list.className = "review-item-list";
      for (const issue of issues) {
        const row = document.createElement("li");
        row.className = "review-item review-item-issue";
        row.append(createIssueItem(issue, requestResolve));
        list.append(row);
      }
      issueSection.append(list);
    }

    if (changes.length > 0) {
      const changeSection = addSection("Pending changes");
      selectionStatus = document.createElement("p");
      selectionStatus.className = "review-selection-status";
      changeSection.append(selectionStatus);
      const list = document.createElement("ul");
      list.className = "review-item-list";
      for (const change of changes) {
        const row = document.createElement("li");
        row.className = "review-item review-item-change";
        row.dataset.reviewState = change.blocking ? "blocked" : "ready";
        row.append(
          change.blocking
            ? createBlockedChange(change, requestResolve)
            : createSelectableChange(
                change,
                selectedIds,
                manuallyDeselectedIds,
                syncSelectionState,
              ),
        );
        list.append(row);
      }
      changeSection.append(list);
    }

    if (issues.length == 0 && changes.length == 0) {
      const empty = document.createElement("p");
      empty.textContent = "There are no pending changes or active issues.";
      content.append(empty);
    }

    syncSelectionState();
  };

  const refresh = () => {
    issues = [...getIssues()];
    changes = [...getChanges()];
    syncSelectedIds();
    render();
  };

  refreshButton.addEventListener("click", () => {
    refresh();
  });

  refresh();

  return {
    content,
    bindDialog(dialogContext) {
      title = dialogContext?.title ?? null;
      cancelButton = dialogContext?.cancel ?? null;
      confirmButton = dialogContext?.confirm ?? null;
      notificationsCon = dialogContext?.notificationsCon ?? null;
      headerActions = dialogContext?.headerActions ?? null;
      if (headerActions) {
        headerActions.replaceChildren(refreshButton);
      }
      syncSelectionState();
    },
    refresh,
    unbindDialog() {
      if (headerActions) {
        headerActions.replaceChildren();
      }
      title = null;
      cancelButton = null;
      confirmButton = null;
      notificationsCon = null;
      headerActions = null;
    },
    getSelectedChanges() {
      return selectedChanges();
    },
    hasSelectableChanges() {
      return hasReadyChanges();
    },
    getState() {
      return {
        changes: [...changes],
        issues: [...issues],
        titleText: titleText(),
      };
    },
  };
}

export { createReviewDialog };
