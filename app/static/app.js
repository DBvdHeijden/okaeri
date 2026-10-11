(() => {
  const root = document.documentElement;

  // Theme: explicit choice overrides prefers-color-scheme.
  const currentTheme = () =>
    root.dataset.theme ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  for (const btn of document.querySelectorAll("[data-theme-toggle]")) {
    btn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      const apply = () => {
        root.dataset.theme = next;
        try { localStorage.setItem("theme", next); } catch (e) {}
      };
      const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!document.startViewTransition || reduced) return apply();
      // Dark drops down over the page; light pulls it back up.
      root.dataset.themeTransition = next === "dark" ? "down" : "up";
      document.startViewTransition(apply).finished.finally(() => {
        delete root.dataset.themeTransition;
      });
    });
  }

  // Hide / undo: the server records it; collapse the row in place instead of reloading.
  document.addEventListener("submit", (e) => {
    const row = e.target.closest(".row");
    if (!row) return;
    e.preventDefault();
    fetch(e.target.action, { method: "POST", redirect: "manual" });
    const hiding = e.target.matches("[data-hide]");
    row.querySelector(".row-body").hidden = hiding;
    row.querySelector(".row-hidden").hidden = !hiding;
    row.querySelector(hiding ? "[data-undo] button" : "[data-hide] button").focus();
  });

  // Onboarding
  const form = document.querySelector("[data-onboarding]");
  if (form) {
    const count = form.querySelector("[data-selected-count]");
    const updateCount = () => {
      const n = form.querySelectorAll('input[name="sources"]:checked').length;
      count.textContent = `${n} selected`;
    };
    form.addEventListener("change", updateCount);
    updateCount();

    const search = document.querySelector("[data-source-search]");
    const noResults = form.querySelector("[data-no-results]");
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      let any = false;
      for (const group of form.querySelectorAll("[data-group]")) {
        let visible = 0;
        for (const source of group.querySelectorAll(".source")) {
          const match = source.dataset.name.includes(q);
          source.parentElement.hidden = !match;
          if (match) visible++;
        }
        group.hidden = visible === 0;
        any ||= visible > 0;
      }
      noResults.hidden = any;
    });

    const notice = document.querySelector("[data-notice]");
    for (const btn of document.querySelectorAll("[data-not-yet]")) {
      btn.addEventListener("click", () => {
        notice.textContent = `${btn.textContent.trim()}: not available yet.`;
      });
    }
  }
})();
