/* Empty, local-only connection preview for the cockpit demo. */
(function () {
  "use strict";

  const modal = document.querySelector("[data-setup-dialog]");
  if (!modal) return;

  const closeButton = modal.querySelector("[data-setup-close]");
  const firstProvider = modal.querySelector("[data-connect-provider]");
  const notice = modal.querySelector("[data-setup-notice]");
  let returnFocus = null;

  function setOpen(open) {
    modal.hidden = !open;
    document.body.classList.toggle("setup-open", open);
    if (open) {
      returnFocus = document.activeElement;
      if (notice) notice.textContent = "";
      if (firstProvider) firstProvider.focus();
    } else if (returnFocus && typeof returnFocus.focus === "function") {
      returnFocus.focus();
    }
  }

  document.querySelectorAll("[data-connect-open]").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      setOpen(true);
    });
  });

  modal.querySelectorAll("[data-connect-provider]").forEach(function (button) {
    button.addEventListener("click", function () {
      const label = button.textContent.trim();
      if (notice) {
        notice.textContent = label +
          " is a guided preview only. No connection is started or saved.";
      }
    });
  });

  if (closeButton) closeButton.addEventListener("click", function () {
    setOpen(false);
  });
  modal.addEventListener("click", function (event) {
    if (event.target === modal) setOpen(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modal.hidden) setOpen(false);
  });
})();
