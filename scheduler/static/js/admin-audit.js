(() => {
  const root = document.querySelector(".rbac-audit-page");
  if (!(root instanceof HTMLElement)) {
    return;
  }

  const forms = root.querySelectorAll(".rbac-audit-filters");
  if (forms.length === 0) {
    return;
  }

  const submitTimers = new Map();
  const requestControllers = new Map();
  const submitDelayMs = 280;
  const path = window.location.pathname;

  const parseNumber = (value, fallback = 0) => {
    const parsed = Number.parseInt(String(value ?? ""), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const textValue = (value, fallback = "") => {
    if (typeof value !== "string") {
      return fallback;
    }
    return value;
  };

  const getFieldValue = (form, name, fallback = "") => {
    if (!(form instanceof HTMLFormElement)) {
      return fallback;
    }
    const field = form.elements.namedItem(name);
    if (field instanceof HTMLInputElement) {
      if (field.type === "checkbox") {
        return field.checked ? field.value : "";
      }
      return field.value;
    }
    if (field instanceof HTMLSelectElement) {
      return field.value;
    }
    return fallback;
  };

  const setFieldValue = (form, name, value) => {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const field = form.elements.namedItem(name);
    if (
      field instanceof HTMLInputElement ||
      field instanceof HTMLSelectElement
    ) {
      field.value = value;
    }
  };

  const defaultRbacLimit = Math.max(
    1,
    parseNumber(root.dataset.rbacAuditDefaultLimit, 10),
  );
  const defaultAppErrorLimit = Math.max(
    1,
    parseNumber(root.dataset.appErrorDefaultLimit, 10),
  );
  const defaultEmailLimit = Math.max(
    1,
    parseNumber(root.dataset.emailAuditDefaultLimit, 10),
  );
  const defaultShowMoreStep = Math.max(
    1,
    parseNumber(root.dataset.auditShowMoreIncrement, 20),
  );
  const globalMaxLimit = Math.max(
    1,
    parseNumber(root.dataset.auditMaxLimit, 200),
  );

  const mapEmailQueryParams = (form) => {
    const params = new URLSearchParams();
    params.set("scope", getFieldValue(form, "email_scope", "all"));
    params.set("entity", getFieldValue(form, "email_entity", ""));
    params.set("status", getFieldValue(form, "email_status", "all"));
    params.set("issue_state", getFieldValue(form, "email_issue_state", "all"));
    params.set("search", getFieldValue(form, "email_search", ""));
    params.set(
      "search_field",
      getFieldValue(form, "email_search_field", "all"),
    );
    params.set(
      "limit",
      getFieldValue(form, "email_limit", String(defaultEmailLimit)),
    );
    return params;
  };

  const mapAppErrorQueryParams = (form) => {
    const params = new URLSearchParams();
    params.set("actor", getFieldValue(form, "app_error_actor", ""));
    params.set(
      "reference_id",
      getFieldValue(form, "app_error_reference_id", ""),
    );
    params.set(
      "exception_type",
      getFieldValue(form, "app_error_exception_type", ""),
    );
    params.set("where_path", getFieldValue(form, "app_error_where_path", ""));
    params.set("search", getFieldValue(form, "app_error_search", ""));
    params.set(
      "limit",
      getFieldValue(form, "app_error_limit", String(defaultAppErrorLimit)),
    );
    return params;
  };

  const mapRbacQueryParams = (form) => {
    const params = new URLSearchParams();
    params.set("scope", getFieldValue(form, "audit_scope", "all"));
    params.set("entity", getFieldValue(form, "audit_entity", ""));
    params.set("search", getFieldValue(form, "audit_search", ""));
    params.set(
      "search_field",
      getFieldValue(form, "audit_search_field", "all"),
    );
    params.set(
      "limit",
      getFieldValue(form, "audit_limit", String(defaultRbacLimit)),
    );
    return params;
  };

  const rowCell = (row, value) => {
    const cell = document.createElement("td");
    cell.textContent = textValue(value, "").trim() || "-";
    row.appendChild(cell);
  };

  const renderRbacRows = (events) => {
    const body = document.getElementById("rbac-audit-body");
    if (!(body instanceof HTMLTableSectionElement)) {
      return;
    }
    body.textContent = "";
    const fragment = document.createDocumentFragment();
    events.forEach((event) => {
      const row = document.createElement("tr");
      rowCell(row, event.when);
      rowCell(row, event.action);
      rowCell(row, event.actor);
      rowCell(row, event.ip);
      rowCell(row, event.where);
      rowCell(row, event.how);
      rowCell(row, event.what);
      fragment.appendChild(row);
    });
    body.appendChild(fragment);
  };

  const renderEmailRows = (events) => {
    const body = document.getElementById("email-audit-body");
    if (!(body instanceof HTMLTableSectionElement)) {
      return;
    }
    body.textContent = "";
    const fragment = document.createDocumentFragment();
    events.forEach((event) => {
      const row = document.createElement("tr");
      rowCell(row, event.when);
      rowCell(row, event.status);
      rowCell(row, event.issue_state);
      rowCell(row, event.issue_key);
      rowCell(row, event.action);
      rowCell(row, event.actor);
      rowCell(row, event.recipient);
      rowCell(row, event.subject);
      rowCell(row, event.where);
      rowCell(row, event.how);
      rowCell(row, event.details);
      fragment.appendChild(row);
    });
    body.appendChild(fragment);
  };

  const renderAppErrorRows = (events) => {
    const body = document.getElementById("app-error-body");
    if (!(body instanceof HTMLTableSectionElement)) {
      return;
    }
    body.textContent = "";
    const fragment = document.createDocumentFragment();
    events.forEach((event) => {
      const row = document.createElement("tr");
      rowCell(row, event.when);
      rowCell(row, event.reference_id);
      rowCell(row, event.actor);
      rowCell(
        row,
        `${textValue(event.method, "").trim()} ${textValue(
          event.where,
          "",
        ).trim()}`.trim(),
      );
      rowCell(row, event.exception_type);
      rowCell(row, event.message);
      rowCell(row, event.fingerprint);

      const detailCell = document.createElement("td");
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "view";
      details.appendChild(summary);

      const detailsLines = [
        `endpoint: ${textValue(event.endpoint, "").trim() || "-"}`,
        `status: ${parseNumber(event.status_code, 500)}`,
        `ip: ${textValue(event.ip, "").trim() || "-"}`,
        `user agent: ${textValue(event.user_agent, "").trim() || "-"}`,
      ];
      detailsLines.forEach((line) => {
        const paragraph = document.createElement("p");
        paragraph.textContent = line;
        details.appendChild(paragraph);
      });

      const contextPre = document.createElement("pre");
      contextPre.textContent = JSON.stringify(
        typeof event.request_context === "object" &&
          event.request_context !== null
          ? event.request_context
          : {},
        null,
        2,
      );
      details.appendChild(contextPre);

      const tracePre = document.createElement("pre");
      tracePre.textContent = textValue(event.stack_trace, "").trim() || "-";
      details.appendChild(tracePre);

      detailCell.appendChild(details);
      row.appendChild(detailCell);
      fragment.appendChild(row);
    });
    body.appendChild(fragment);
  };

  const syncQueryString = () => {
    const rbacForm = document.getElementById("rbac-audit-filters");
    const appErrorForm = document.getElementById("app-error-filters");
    const emailForm = document.getElementById("email-audit-filters");
    const notificationForm = document.getElementById(
      "notification-issues-filters",
    );
    if (
      !(rbacForm instanceof HTMLFormElement) &&
      !(appErrorForm instanceof HTMLFormElement) &&
      !(emailForm instanceof HTMLFormElement) &&
      !(notificationForm instanceof HTMLFormElement)
    ) {
      return;
    }
    const params = new URLSearchParams();
    if (rbacForm instanceof HTMLFormElement) {
      params.set("audit_scope", getFieldValue(rbacForm, "audit_scope", "all"));
      params.set("audit_entity", getFieldValue(rbacForm, "audit_entity", ""));
      params.set("audit_search", getFieldValue(rbacForm, "audit_search", ""));
      params.set(
        "audit_search_field",
        getFieldValue(rbacForm, "audit_search_field", "all"),
      );
      params.set(
        "audit_limit",
        getFieldValue(rbacForm, "audit_limit", String(defaultRbacLimit)),
      );
    }
    if (appErrorForm instanceof HTMLFormElement) {
      params.set(
        "app_error_actor",
        getFieldValue(appErrorForm, "app_error_actor", ""),
      );
      params.set(
        "app_error_reference_id",
        getFieldValue(appErrorForm, "app_error_reference_id", ""),
      );
      params.set(
        "app_error_exception_type",
        getFieldValue(appErrorForm, "app_error_exception_type", ""),
      );
      params.set(
        "app_error_where_path",
        getFieldValue(appErrorForm, "app_error_where_path", ""),
      );
      params.set(
        "app_error_search",
        getFieldValue(appErrorForm, "app_error_search", ""),
      );
      params.set(
        "app_error_limit",
        getFieldValue(
          appErrorForm,
          "app_error_limit",
          String(defaultAppErrorLimit),
        ),
      );
    }
    if (emailForm instanceof HTMLFormElement) {
      params.set("email_scope", getFieldValue(emailForm, "email_scope", "all"));
      params.set("email_entity", getFieldValue(emailForm, "email_entity", ""));
      params.set(
        "email_status",
        getFieldValue(emailForm, "email_status", "all"),
      );
      params.set(
        "email_issue_state",
        getFieldValue(emailForm, "email_issue_state", "all"),
      );
      params.set("email_search", getFieldValue(emailForm, "email_search", ""));
      params.set(
        "email_search_field",
        getFieldValue(emailForm, "email_search_field", "all"),
      );
      params.set(
        "email_limit",
        getFieldValue(emailForm, "email_limit", String(defaultEmailLimit)),
      );
    }
    if (notificationForm instanceof HTMLFormElement) {
      params.set(
        "notification_state_filter",
        getFieldValue(notificationForm, "notification_state_filter", "1"),
      );
      params.set(
        "notification_include_open",
        getFieldValue(notificationForm, "notification_include_open", ""),
      );
      params.set(
        "notification_include_resolved",
        getFieldValue(notificationForm, "notification_include_resolved", ""),
      );
      params.set(
        "notification_include_ignored",
        getFieldValue(notificationForm, "notification_include_ignored", ""),
      );
      params.set(
        "notification_category",
        getFieldValue(notificationForm, "notification_category", "all"),
      );
      params.set(
        "notification_search",
        getFieldValue(notificationForm, "notification_search", ""),
      );
      params.set(
        "notification_search_field",
        getFieldValue(notificationForm, "notification_search_field", "all"),
      );
    }
    const query = params.toString();
    const next = query === "" ? path : `${path}?${query}`;
    window.history.replaceState({}, "", next);
  };

  const applyAuditPayload = (form, payload) => {
    const kind = form.dataset.auditKind;
    const count = Math.max(0, parseNumber(payload.count, 0));
    const defaultLimit =
      kind === "email"
        ? defaultEmailLimit
        : kind === "app-error"
        ? defaultAppErrorLimit
        : defaultRbacLimit;
    const limit = Math.max(1, parseNumber(payload.limit, defaultLimit));
    if (kind === "rbac") {
      setFieldValue(form, "audit_limit", String(limit));
      renderRbacRows(Array.isArray(payload.events) ? payload.events : []);
      const empty = document.getElementById("rbac-audit-empty");
      const tableWrap = document.getElementById("rbac-audit-table-wrap");
      const showMoreWrap = document.getElementById("rbac-audit-show-more-wrap");
      if (empty instanceof HTMLElement) {
        empty.hidden = count > 0;
      }
      if (tableWrap instanceof HTMLElement) {
        tableWrap.hidden = count === 0;
      }
      if (showMoreWrap instanceof HTMLElement) {
        showMoreWrap.hidden = !(count === limit && limit < globalMaxLimit);
      }
    } else if (kind === "app-error") {
      setFieldValue(form, "app_error_limit", String(limit));
      renderAppErrorRows(Array.isArray(payload.events) ? payload.events : []);
      const empty = document.getElementById("app-error-empty");
      const tableWrap = document.getElementById("app-error-table-wrap");
      const showMoreWrap = document.getElementById("app-error-show-more-wrap");
      if (empty instanceof HTMLElement) {
        empty.hidden = count > 0;
      }
      if (tableWrap instanceof HTMLElement) {
        tableWrap.hidden = count === 0;
      }
      if (showMoreWrap instanceof HTMLElement) {
        showMoreWrap.hidden = !(count === limit && limit < globalMaxLimit);
      }
    } else if (kind === "email") {
      setFieldValue(form, "email_limit", String(limit));
      renderEmailRows(Array.isArray(payload.events) ? payload.events : []);
      const empty = document.getElementById("email-audit-empty");
      const tableWrap = document.getElementById("email-audit-table-wrap");
      const showMoreWrap = document.getElementById(
        "email-audit-show-more-wrap",
      );
      if (empty instanceof HTMLElement) {
        empty.hidden = count > 0;
      }
      if (tableWrap instanceof HTMLElement) {
        tableWrap.hidden = count === 0;
      }
      if (showMoreWrap instanceof HTMLElement) {
        showMoreWrap.hidden = !(count === limit && limit < globalMaxLimit);
      }
    }
    syncQueryString();
  };

  const fetchAudit = async (form) => {
    const endpoint = textValue(form.dataset.auditEndpoint, "").trim();
    if (endpoint === "") {
      return;
    }

    const kind = form.dataset.auditKind;
    const params =
      kind === "email"
        ? mapEmailQueryParams(form)
        : kind === "app-error"
        ? mapAppErrorQueryParams(form)
        : mapRbacQueryParams(form);

    const activeController = requestControllers.get(form);
    if (activeController instanceof AbortController) {
      activeController.abort();
    }
    const controller = new AbortController();
    requestControllers.set(form, controller);

    try {
      const response = await fetch(`${endpoint}?${params.toString()}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      applyAuditPayload(form, payload);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      console.error("Failed to refresh audit feed", error);
    } finally {
      const current = requestControllers.get(form);
      if (current === controller) {
        requestControllers.delete(form);
      }
    }
  };

  const queueFetch = (form, delay = submitDelayMs) => {
    const currentTimer = submitTimers.get(form);
    if (currentTimer != null) {
      window.clearTimeout(currentTimer);
    }
    const timer = window.setTimeout(
      () => {
        submitTimers.delete(form);
        fetchAudit(form);
      },
      Math.max(0, delay),
    );
    submitTimers.set(form, timer);
  };

  forms.forEach((form) => {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const currentTimer = submitTimers.get(form);
      if (currentTimer != null) {
        window.clearTimeout(currentTimer);
        submitTimers.delete(form);
      }
      fetchAudit(form);
    });
    form.addEventListener("change", (event) => {
      const target = event.target;
      if (
        (target instanceof HTMLInputElement ||
          target instanceof HTMLSelectElement) &&
        target.type !== "hidden" &&
        target.type !== "submit"
      ) {
        queueFetch(form, 0);
      }
    });
    form.addEventListener("input", (event) => {
      const target = event.target;
      if (
        target instanceof HTMLInputElement &&
        (target.type === "text" ||
          target.type === "search" ||
          target.type === "number")
      ) {
        queueFetch(form);
      }
    });
  });

  const notificationForm = document.getElementById(
    "notification-issues-filters",
  );
  let notificationSubmitTimer = null;
  const queueNotificationSubmit = (delay = submitDelayMs) => {
    if (!(notificationForm instanceof HTMLFormElement)) {
      return;
    }
    if (notificationSubmitTimer != null) {
      window.clearTimeout(notificationSubmitTimer);
    }
    notificationSubmitTimer = window.setTimeout(
      () => {
        notificationSubmitTimer = null;
        notificationForm.requestSubmit();
      },
      Math.max(0, delay),
    );
  };

  if (notificationForm instanceof HTMLFormElement) {
    notificationForm.addEventListener("change", (event) => {
      const target = event.target;
      if (
        (target instanceof HTMLInputElement ||
          target instanceof HTMLSelectElement) &&
        target.type !== "hidden" &&
        target.type !== "submit"
      ) {
        queueNotificationSubmit(0);
      }
    });
    notificationForm.addEventListener("input", (event) => {
      const target = event.target;
      if (
        target instanceof HTMLInputElement &&
        (target.type === "text" ||
          target.type === "search" ||
          target.type === "number")
      ) {
        queueNotificationSubmit();
      }
    });
  }

  const attachSearchPlaceholder = (
    searchInputId,
    searchFieldId,
    placeholderByField,
  ) => {
    const searchInput = document.getElementById(searchInputId);
    const searchField = document.getElementById(searchFieldId);
    if (
      !(searchInput instanceof HTMLInputElement) ||
      !(searchField instanceof HTMLSelectElement)
    ) {
      return;
    }
    const syncPlaceholder = () => {
      const selectedField = searchField.value;
      searchInput.placeholder =
        placeholderByField[selectedField] || placeholderByField.all;
    };
    syncPlaceholder();
    searchField.addEventListener("change", syncPlaceholder);
    searchField.addEventListener("input", syncPlaceholder);
  };

  attachSearchPlaceholder("rbac-audit-search", "rbac-audit-search-field", {
    all: "action, actor, details, where, how, ip, entity ids",
    action: "for example: user.device.update",
    actor: "for example: test-admin",
    entity: "group, device, or user id",
    how: "for example: rbac-explorer-batch",
    ip: "for example: 198.51.100.7",
    what: "details text",
    where: "for example: /rbac?scope=group&entity=DEV",
  });
  attachSearchPlaceholder("email-audit-search", "email-audit-search-field", {
    all: "action, actor, recipient, subject, details, issue key",
    action: "for example: email.issue.resolved",
    actor: "for example: test-admin",
    details: "details text",
    recipient: "name@example.com",
    issue_key: "for example: join-group:DEV:incident",
    subject: "subject text",
  });
  attachSearchPlaceholder("notification-search", "notification-search-field", {
    all: "title, detail, issue key, category",
    title: "issue title text",
    detail: "issue detail text",
    issue_key: "for example: join-group:DEV:user",
    category: "for example: top priority",
  });

  const showMoreClick = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }

    const form = document.getElementById(
      target.getAttribute("data-form") || "",
    );
    if (!(form instanceof HTMLFormElement)) {
      return;
    }

    const limitInput = document.getElementById(
      target.getAttribute("data-limit-input") || "",
    );
    if (!(limitInput instanceof HTMLInputElement)) {
      return;
    }

    const step = Math.max(
      1,
      parseNumber(target.getAttribute("data-limit-step"), defaultShowMoreStep),
    );
    const max = Math.max(
      parseNumber(target.getAttribute("data-limit-max"), globalMaxLimit),
      parseNumber(limitInput.value, 0),
    );
    const currentLimit = parseNumber(limitInput.value, 0);
    const nextLimit = Math.min(max, currentLimit + step);
    if (nextLimit <= currentLimit) {
      return;
    }

    const currentTimer = submitTimers.get(form);
    if (currentTimer != null) {
      window.clearTimeout(currentTimer);
      submitTimers.delete(form);
    }
    limitInput.value = String(nextLimit);
    fetchAudit(form);
  };

  const showMoreButtons = root.querySelectorAll(".admin-show-more-button");
  showMoreButtons.forEach((button) => {
    button.addEventListener("click", showMoreClick);
  });

  syncQueryString();
})();
