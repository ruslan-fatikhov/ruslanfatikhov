(() => {
  const openButton = document.querySelector("[data-action='open-search']");
  const closeButton = document.querySelector("[data-action='close-search']");
  const panel = document.querySelector("[data-search]");
  const input = document.querySelector("[data-search-input]");
  const results = document.querySelector("[data-search-results]");
  let indexPromise = null;
  let generation = 0;

  const openSearch = () => {
    if (!panel) {
      return;
    }
    panel.hidden = false;
    window.siteDialogs.open(panel);
    input.focus();
  };

  const closeSearch = () => {
    if (!panel) {
      return;
    }
    generation += 1;
    panel.hidden = true;
    window.siteDialogs.close(panel);
    input.value = "";
    results.innerHTML = "";
  };

  const fetchIndex = () => {
    if (!indexPromise) {
      indexPromise = fetch("/search.json")
        .then((response) => {
          if (!response.ok) throw new Error(`Search HTTP ${response.status}`);
          return response.json();
        })
        .then((data) => {
          if (!Array.isArray(data)) throw new Error("Invalid search index");
          return data;
        })
        .catch((error) => { indexPromise = null; throw error; });
    }
    return indexPromise;
  };

  const getLang = () => document.documentElement.dataset.lang || "ru";

  const renderResults = (items, query) => {
    results.innerHTML = "";
    if (!query) {
      return;
    }
    const fragment = document.createDocumentFragment();
    items.forEach((item) => {
      const link = document.createElement("a");
      link.href = `/${item.slug}?lang=${getLang()}`;
      link.className = "card";
      const headline = item.headline[getLang()] || item.headline.ru || item.slug;
      const subline = item.subline?.[getLang()] || item.subline?.ru || "";
      const body = document.createElement("div");
      body.className = "card__body";
      for (const [className, text] of [["card__title", headline], ["card__meta", subline]]) {
        const node = document.createElement("div");
        node.className = className;
        node.textContent = text;
        body.appendChild(node);
      }
      link.appendChild(body);
      fragment.appendChild(link);
    });
    results.appendChild(fragment);
  };

  const handleInput = async (event) => {
    const query = event.target.value.trim().toLowerCase();
    const current = ++generation;
    if (!query) { results.replaceChildren(); return; }
    try {
      const data = await fetchIndex();
      if (current !== generation || panel.hidden) return;
      const filtered = data.filter((item) => {
        const inHeadline = Object.values(item.headline || {}).some((value) =>
          value.toLowerCase().includes(query)
        );
        const inContent = Object.values(item.content || {}).some((value) =>
          value.toLowerCase().includes(query)
        );
        return inHeadline || inContent;
      });
      renderResults(filtered, query);
    } catch (error) {
      if (current === generation && !panel.hidden) {
        results.textContent = "Не удалось загрузить поиск. Попробуйте ещё раз.";
      }
    }
  };

  if (openButton) {
    openButton.addEventListener("click", openSearch);
  }
  if (closeButton) {
    closeButton.addEventListener("click", closeSearch);
  }
  if (panel) {
    panel.addEventListener("click", (event) => {
      if (event.target === panel) {
        closeSearch();
      }
    });
  }
  if (input) {
    input.addEventListener("input", handleInput);
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSearch();
    }
  });
})();
