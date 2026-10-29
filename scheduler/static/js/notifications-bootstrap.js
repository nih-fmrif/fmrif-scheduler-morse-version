import { installGlobalNotifier } from "./notifications.js";

function initNotifications() {
  installGlobalNotifier();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initNotifications, {
    once: true,
  });
} else {
  initNotifications();
}
