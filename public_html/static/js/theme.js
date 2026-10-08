(() => {
  const root = document.documentElement;
  const buttons = document.querySelectorAll("button[data-theme]");

  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    localStorage.setItem("theme", theme);
    buttons.forEach((button) => {
      button.dataset.active = button.dataset.theme === theme ? "true" : "false";
    });
  };

  const stored = localStorage.getItem("theme");
  applyTheme(stored || "light");

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      applyTheme(button.dataset.theme);
    });
  });
})();
