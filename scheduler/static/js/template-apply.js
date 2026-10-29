const container = document.querySelector(".apply-helper");
const templates = document.querySelector("#templates");
const form = document.querySelector(".template-apply");
const submitButton = form?.querySelector("button[type='submit']");

if (container && templates) {
  const readyTemplates = new Set();
  const blockedTemplates = new Map();

  container.querySelectorAll("button[data-tc]").forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    const templateCode = button.dataset.tc || "";
    if (!templateCode) {
      return;
    }
    if (button.disabled) {
      blockedTemplates.set(templateCode, button.title || "repair required");
      return;
    }
    readyTemplates.add(templateCode);
  });

  const normalizeCodes = () =>
    Array.from((templates.value || "").replace(/\s+/g, ""))
      .map((code) => code.trim())
      .filter(Boolean);

  const validationMessage = () => {
    const codes = normalizeCodes();
    if (!codes.length) {
      return "";
    }

    const blocked = [];
    const unavailable = [];

    codes.forEach((code) => {
      if (readyTemplates.has(code)) {
        return;
      }
      if (blockedTemplates.has(code)) {
        blocked.push(`${code}: ${blockedTemplates.get(code)}`);
        return;
      }
      unavailable.push(code);
    });

    const messages = [];
    if (blocked.length) {
      messages.push(
        `repair required template codes cannot be applied: ${blocked.join(
          " | ",
        )}`,
      );
    }
    if (unavailable.length) {
      messages.push(
        `unknown or unavailable template codes: ${unavailable.join(", ")}`,
      );
    }
    return messages.join(" ");
  };

  const syncValidity = () => {
    templates.setCustomValidity(validationMessage());
    return !templates.validationMessage;
  };

  const blockInvalidSubmit = (event) => {
    if (syncValidity()) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    templates.reportValidity();
  };

  container.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest("button[data-tc]");
    if (!button) {
      return;
    }
    if (button.disabled) {
      return;
    }
    event.preventDefault();
    templates.value += button.dataset.tc || "";
    syncValidity();
  });

  templates.addEventListener("input", syncValidity);
  templates.addEventListener("change", syncValidity);
  form?.addEventListener("submit", blockInvalidSubmit);
  submitButton?.addEventListener("click", blockInvalidSubmit, true);
  syncValidity();
  container.classList.add("js-loaded");
}
