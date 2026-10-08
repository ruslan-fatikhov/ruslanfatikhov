(() => {
  const list = document.querySelectorAll("[data-feed-item]");
  const button = document.querySelector("[data-feed-more]");
  const limit = 7;

  if (!list.length || !button) {
    return;
  }

  list.forEach((item, index) => {
    if (index >= limit) {
      item.hidden = true;
    }
  });

  if (list.length <= limit) {
    button.hidden = true;
  }

  button.addEventListener("click", () => {
    list.forEach((item) => {
      item.hidden = false;
    });
    button.hidden = true;
  });
})();
