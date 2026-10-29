function text(value) {
  if (value == null) {
    return "";
  }
  return String(value);
}

function normalizeLevel(rawLevel) {
  const normalized = text(rawLevel).trim().toLowerCase();
  if (normalized === "") {
    return "info";
  }

  const token = normalized.replace(/^(msg|flash)-/, "");
  if (
    token === "error" ||
    token === "danger" ||
    token === "failed" ||
    token === "failure"
  ) {
    return "error";
  }
  if (token === "warning" || token === "warn") {
    return "warning";
  }
  if (
    token === "message" ||
    token === "success" ||
    token === "ok" ||
    token === "done"
  ) {
    return "success";
  }
  if (token === "info" || token === "notice") {
    return "info";
  }
  return "info";
}

function inferLevelFromItem(item) {
  if (!(item instanceof HTMLElement)) {
    return "info";
  }

  const datasetLevel = text(item.dataset.level || item.dataset.category);
  if (datasetLevel !== "") {
    return normalizeLevel(datasetLevel);
  }

  for (const className of item.classList) {
    const level = normalizeLevel(className);
    if (level !== "info" || className.includes("info")) {
      return level;
    }
  }

  return "info";
}

function ensureFeedbackContainer() {
  const existing = document.getElementById("app-feedback");
  if (existing instanceof HTMLElement) {
    return existing;
  }

  const container = document.createElement("div");
  container.id = "app-feedback";
  container.className = "app-feedback";
  container.setAttribute("aria-live", "polite");
  document.body.append(container);
  return container;
}

function createNotifier(container, { fallbackStatusNode = null } = {}) {
  const fallback = (message, level) => {
    if (!(fallbackStatusNode instanceof HTMLElement)) {
      return;
    }
    fallbackStatusNode.textContent = text(message);
    fallbackStatusNode.dataset.state = level === "success" ? "ok" : level;
  };

  if (!(container instanceof HTMLElement)) {
    return {
      notify(message, level = "info") {
        fallback(message, level);
      },
      clear() {},
    };
  }

  let issued = 0;
  const maxVisible = 5;

  const dismissToast = (toast) => {
    if (!(toast instanceof HTMLElement)) {
      return;
    }
    const timeoutId = Number(toast.dataset.timeoutId || 0);
    if (timeoutId > 0) {
      window.clearTimeout(timeoutId);
    }
    toast.remove();
  };

  const trimVisibleToasts = () => {
    const toasts = container.querySelectorAll(".app-toast");
    if (toasts.length <= maxVisible) {
      return;
    }
    for (let index = 0; index < toasts.length - maxVisible; index += 1) {
      dismissToast(toasts[index]);
    }
  };

  return {
    notify(message, level = "info", options = {}) {
      const normalizedLevel = normalizeLevel(level);
      const textMessage = text(message).trim();
      if (textMessage === "") {
        return;
      }

      const toast = document.createElement("article");
      toast.className = "app-toast";
      toast.dataset.state = normalizedLevel;
      toast.dataset.id = String(issued);
      issued += 1;
      toast.setAttribute(
        "role",
        normalizedLevel === "error" ? "alert" : "status",
      );

      const content = document.createElement("p");
      content.className = "app-toast-message";
      content.textContent = textMessage;

      const dismiss = document.createElement("button");
      dismiss.type = "button";
      dismiss.className = "app-toast-dismiss";
      dismiss.setAttribute("aria-label", "dismiss notification");
      dismiss.textContent = "x";
      dismiss.addEventListener("click", () => dismissToast(toast));

      toast.append(content, dismiss);
      container.append(toast);
      trimVisibleToasts();

      const sticky = options.sticky === true || normalizedLevel === "error";
      const timeoutMs =
        Number(options.timeoutMs) > 0
          ? Number(options.timeoutMs)
          : normalizedLevel === "success"
          ? 4200
          : 5600;
      if (!sticky) {
        const timeoutId = window.setTimeout(
          () => dismissToast(toast),
          timeoutMs,
        );
        toast.dataset.timeoutId = String(timeoutId);
      }
    },
    clear() {
      container.replaceChildren();
    },
  };
}

export function getAppNotifier(options = {}) {
  const globalWindow = window;
  if (globalWindow.__appNotifier) {
    return globalWindow.__appNotifier;
  }
  const notifier = createNotifier(ensureFeedbackContainer(), options);
  globalWindow.__appNotifier = notifier;
  globalWindow.notifyApp = (message, level = "info", notifyOptions = {}) => {
    notifier.notify(message, level, notifyOptions);
  };
  return notifier;
}

export function consumeFlashMessages(notifier = getAppNotifier()) {
  const sections = document.querySelectorAll(".flash-messages");
  sections.forEach((section) => {
    if (!(section instanceof HTMLElement)) {
      return;
    }
    if (section.dataset.toastConsumed === "1") {
      return;
    }

    let items = Array.from(section.querySelectorAll("li"));
    if (items.length === 0) {
      items = Array.from(section.children);
    }
    if (items.length === 0) {
      items = [section];
    }

    items.forEach((item) => {
      if (!(item instanceof HTMLElement)) {
        return;
      }
      const message = text(item.textContent).replace(/\s+/g, " ").trim();
      if (message === "") {
        return;
      }
      notifier.notify(message, inferLevelFromItem(item));
    });

    section.dataset.toastConsumed = "1";
    section.remove();
  });
}

export function installGlobalNotifier(options = {}) {
  const notifier = getAppNotifier(options);
  consumeFlashMessages(notifier);
  return notifier;
}
