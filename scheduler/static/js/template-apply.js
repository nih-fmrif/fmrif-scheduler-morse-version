const container = document.querySelector(".apply-helper");
const templates = document.querySelector("#templates");

if (container && templates) {
  container.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest("button[data-tc]");
    if (!button) {
      return;
    }
    event.preventDefault();
    templates.value += button.dataset.tc || "";
  });

  container.classList.add("js-loaded");
}
