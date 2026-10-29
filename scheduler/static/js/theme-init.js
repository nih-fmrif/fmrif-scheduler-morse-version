(function () {
  const THEME_STORAGE_KEY = "fmrif-theme-preference";
  const root = document.documentElement;

  function read_stored_theme() {
    try {
      const value = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (value === "light" || value === "dark") {
        return value;
      }
    } catch (_error) {
      return null;
    }
    return null;
  }

  const stored_theme = read_stored_theme();
  if (stored_theme) {
    root.dataset.theme = stored_theme;
  } else {
    delete root.dataset.theme;
  }
})();
