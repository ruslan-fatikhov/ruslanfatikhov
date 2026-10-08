(() => {
  const tabs = document.querySelectorAll("[data-cities-tabs] [data-tab]");
  const list = document.querySelector("[data-cities-list]");
  const map = document.querySelector("[data-cities-map]");

  if (!tabs.length || !list || !map) {
    return;
  }

  const applyTab = (tab) => {
    list.dataset.active = tab === "list" ? "true" : "false";
    map.dataset.active = tab === "map" ? "true" : "false";
    tabs.forEach((button) => {
      button.dataset.active = button.dataset.tab === tab ? "true" : "false";
      button.setAttribute("aria-selected", button.dataset.tab === tab ? "true" : "false");
    });
    localStorage.setItem("citiesTab", tab);
    if (tab === "map") {
      window.dispatchEvent(new Event("resize"));
    }
  };

  const stored = localStorage.getItem("citiesTab") || "list";
  applyTab(stored);

  tabs.forEach((button) => {
    button.addEventListener("click", () => {
      applyTab(button.dataset.tab);
    });
  });

  const sheet = document.querySelector("[data-city-sheet]");
  const sheetTitle = document.getElementById("city-sheet-title");
  const sheetCountry = document.querySelector("[data-city-sheet-country]");
  const sheetGallery = document.querySelector("[data-city-sheet-gallery]");
  const closeButtons = document.querySelectorAll("[data-city-sheet-close]");
  const cities = new Map();
  const cityDetails = new Map();
  let closeTimer;

  document.querySelectorAll("[data-city-card]").forEach((card) => {
    cities.set(card.dataset.slug, {
      slug: card.dataset.slug,
      name: card.dataset.name,
      country: card.dataset.country,
    });
  });

  if (!sheet || !sheetTitle || !sheetCountry || !sheetGallery || !cities.size) {
    return;
  }

  const renderGallery = (city) => {
    sheetGallery.replaceChildren();
    const grid = document.createElement("div");
    grid.className = "gallery__grid city-sheet__grid";

    city.gallery.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "gallery__item";
      button.dataset.full = item.full;

      const image = document.createElement("img");
      image.src = item.thumb;
      image.alt = `${city.name} photo ${index + 1}`;
      image.loading = "lazy";
      image.decoding = "async";
      button.appendChild(image);
      grid.appendChild(button);
    });

    sheetGallery.appendChild(grid);
  };

  const renderMessage = (message) => {
    sheetGallery.replaceChildren();
    const status = document.createElement("div");
    status.className = "city-sheet__status";
    status.setAttribute("role", "status");
    status.textContent = message;
    sheetGallery.appendChild(status);
  };

  const loadCity = async (slug) => {
    if (cityDetails.has(slug)) {
      return cityDetails.get(slug);
    }
    const response = await fetch(`/api/cities/${encodeURIComponent(slug)}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error("City not found");
    }
    const city = await response.json();
    cityDetails.set(slug, city);
    return city;
  };

  const openCitySheet = async (slug, options = {}) => {
    const preview = cities.get(slug);
    if (!preview) {
      return false;
    }

    clearTimeout(closeTimer);
    sheetTitle.textContent = preview.name;
    sheetCountry.textContent = preview.country;
    renderMessage("Загружаем фотографии...");
    sheet.hidden = false;
    requestAnimationFrame(() => {
      sheet.dataset.open = "true";
    });
    window.siteDialogs.open(sheet);

    if (options.pushState !== false) {
      const url = new URL(window.location.href);
      url.pathname = `/cities/${slug}`;
      window.history.pushState({ citySheet: slug }, "", url);
    }

    try {
      const city = await loadCity(slug);
      sheetTitle.textContent = city.name;
      sheetCountry.textContent = city.country;
      renderGallery(city);
    } catch (error) {
      renderMessage("Не удалось загрузить фотографии города.");
    }

    return true;
  };

  const closeCitySheet = (options = {}) => {
    if (!sheet || sheet.hidden) {
      return;
    }

    sheet.dataset.open = "false";
    sheetGallery.replaceChildren();
    window.siteDialogs.close(sheet);

    closeTimer = setTimeout(() => {
      if (sheet.dataset.open === "false") {
        sheet.hidden = true;
      }
    }, 220);

    if (options.updateHistory !== false && window.location.pathname.startsWith("/cities/")) {
      const url = new URL(window.location.href);
      url.pathname = "/cities";
      window.history.replaceState({}, "", url);
    }
  };

  document.querySelectorAll("[data-city-card]").forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      openCitySheet(card.dataset.slug);
    });
  });

  closeButtons.forEach((button) => button.addEventListener("click", () => closeCitySheet()));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeCitySheet();
    }
  });
  window.addEventListener("city:open", (event) => openCitySheet(event.detail.slug));
  window.addEventListener("popstate", () => {
    const match = window.location.pathname.match(/^\/cities\/([^/]+)$/);
    if (match) {
      openCitySheet(decodeURIComponent(match[1]), { pushState: false });
    } else {
      closeCitySheet({ updateHistory: false });
    }
  });

  const initialMatch = window.location.pathname.match(/^\/cities\/([^/]+)$/);
  if (initialMatch) {
    openCitySheet(decodeURIComponent(initialMatch[1]), { pushState: false });
  }
})();
