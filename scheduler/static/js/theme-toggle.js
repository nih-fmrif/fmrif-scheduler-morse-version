const THEME_STORAGE_KEY = "fmrif-theme-preference";
const SYSTEM_THEME = "system";
const THEME_OPTIONS = [SYSTEM_THEME, "light", "dark"];

function read_stored_theme() {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (value === "light" || value === "dark") {
      return value;
    }
  } catch (_error) {
    return SYSTEM_THEME;
  }
  return SYSTEM_THEME;
}

function write_stored_theme(theme) {
  try {
    if (theme === SYSTEM_THEME) {
      window.localStorage.removeItem(THEME_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (_error) {
    // Ignore storage failures and keep the in-memory theme active for this page.
  }
}

function get_system_theme(media_query_list) {
  if (media_query_list == null) {
    return "light";
  }
  return media_query_list.matches ? "dark" : "light";
}

function apply_theme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
    return;
  }
  delete document.documentElement.dataset.theme;
}

function describe_theme(theme, media_query_list) {
  if (theme === SYSTEM_THEME) {
    return `Following system (${get_system_theme(media_query_list)})`;
  }
  return `${theme[0].toUpperCase()}${theme.slice(1)} theme active`;
}

function bind_media_query_listener(media_query_list, on_change) {
  if (media_query_list == null) {
    return;
  }
  if (typeof media_query_list.addEventListener === "function") {
    media_query_list.addEventListener("change", on_change);
    return;
  }
  if (typeof media_query_list.addListener === "function") {
    media_query_list.addListener(on_change);
  }
}

function init_theme_toggle() {
  const theme_toggle = document.querySelector("[data-theme-toggle]");
  if (!theme_toggle) {
    return;
  }

  const status = document.querySelector("[data-theme-status]");
  const buttons = Array.from(
    theme_toggle.querySelectorAll("[data-theme-value]"),
  ).filter((button) => THEME_OPTIONS.includes(button.dataset.themeValue));
  const media_query_list =
    typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)")
      : null;
  let current_theme = read_stored_theme();

  const sync_ui = () => {
    apply_theme(current_theme);
    buttons.forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.themeValue === current_theme),
      );
    });
    if (status) {
      status.textContent = describe_theme(current_theme, media_query_list);
    }
  };

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      current_theme = button.dataset.themeValue ?? SYSTEM_THEME;
      write_stored_theme(current_theme);
      sync_ui();
    });
  });

  bind_media_query_listener(media_query_list, () => {
    if (current_theme === SYSTEM_THEME) {
      sync_ui();
    }
  });

  sync_ui();
}

export { init_theme_toggle };
