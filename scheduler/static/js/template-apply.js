const container = document.querySelector(".apply-helper");
const noJsHelper = container?.querySelector(".apply-helper-no-js");
const jsHelper = container?.querySelector(".apply-helper-js");
const templates = document.querySelector("#templates");
const form = document.querySelector(".template-apply");
const submitButton = form?.querySelector("button[data-js-submit]");
const templatesField = templates?.closest("input-set");
const initialServerErrorMessage =
  form?.dataset.hasServerErrors === "1"
    ? form.dataset.serverErrorMessage ||
      templatesField
        ?.querySelector("input-errors input-error span")
        ?.textContent?.trim() ||
      ""
    : "";

const EMPTY_TEMPLATES_MESSAGE = "enter one or more template codes";

if (container && templates) {
  const readyTemplates = new Set();
  const blockedTemplates = new Map();
  let dirty =
    (form?.dataset.initialState || "pristine") != "pristine" ||
    Boolean(initialServerErrorMessage);
  let serverErrorMessage = initialServerErrorMessage;

  if (templates.required) {
    templates.required = false;
    templates.setAttribute("aria-required", "true");
  }

  noJsHelper?.setAttribute("hidden", "");
  jsHelper?.removeAttribute("hidden");

  container.querySelectorAll("button[data-tc]").forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    const templateCode = button.dataset.tc || "";
    if (!templateCode) {
      return;
    }
    if (button.dataset.templateState === "blocking") {
      blockedTemplates.set(templateCode, button.title || "repair required");
      return;
    }
    readyTemplates.add(templateCode);
  });

  const setFieldState = (state) => {
    if (templatesField) {
      templatesField.dataset.fieldState = state;
    }
    if (form) {
      form.dataset.formState = state;
    }
  };

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

  const syncFormState = ({ forSubmit = false } = {}) => {
    const codes = normalizeCodes();
    let state = "pristine";
    let valid = false;

    if (serverErrorMessage) {
      templates.setCustomValidity(serverErrorMessage);
      state = "invalid";
    } else if (!dirty) {
      templates.setCustomValidity("");
      state = "pristine";
    } else if (!codes.length) {
      if (forSubmit) {
        templates.setCustomValidity(EMPTY_TEMPLATES_MESSAGE);
        state = "invalid";
      } else {
        templates.setCustomValidity("");
        state = "empty";
      }
    } else {
      const message = validationMessage();
      if (message) {
        templates.setCustomValidity(message);
        state = "invalid";
      } else {
        templates.setCustomValidity("");
        state = "valid";
        valid = true;
      }
    }

    setFieldState(state);
    if (submitButton instanceof HTMLButtonElement) {
      submitButton.disabled = !valid;
    }
    return valid;
  };

  const blockInvalidSubmit = (event) => {
    dirty = true;
    const clientValid = syncFormState({ forSubmit: true });
    const htmlValid = templates.checkValidity();
    if (clientValid && htmlValid) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    templates.reportValidity();
  };

  const markDirty = () => {
    dirty = true;
    serverErrorMessage = "";
    form?.setAttribute("data-initial-state", "dirty");
    if (form) {
      form.dataset.hasServerErrors = "0";
      form.dataset.serverErrorMessage = "";
    }
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
    if (button.dataset.templateState === "blocking") {
      return;
    }
    event.preventDefault();
    markDirty();
    templates.value += button.dataset.tc || "";
    syncFormState();
  });

  templates.addEventListener("input", () => {
    markDirty();
    syncFormState();
  });
  templates.addEventListener("change", () => {
    markDirty();
    syncFormState();
  });
  form?.addEventListener("submit", blockInvalidSubmit);
  submitButton?.addEventListener("click", blockInvalidSubmit, true);
  syncFormState();
  container.classList.add("js-loaded");
}
