(() => {
  const mapContainer = document.getElementById("map");
  const mapRoot = document.querySelector("[data-cities-map]");
  if (!mapContainer || !mapRoot) {
    return;
  }

  let started = false;
  let map;
  let failed = false;
  const showError = () => {
    failed = true;
    if (map) { map.remove(); map = null; }
    mapContainer.replaceChildren();
    const message = document.createElement("div");
    message.className = "cities__map-empty";
    message.setAttribute("role", "status");
    message.textContent = "Не удалось загрузить карту. Города и фотографии доступны в списке. Попробуйте открыть страницу позже.";
    mapContainer.appendChild(message);
  };
  const start = async () => {
    if (started) return;
    started = true;
    const timeout = setTimeout(showError, 20000);
    try {
      if (!window.OpenFreeMap) throw new Error("Missing OpenFreeMap loader");
      await window.OpenFreeMap.load();
      if (failed) return;
      mapContainer.replaceChildren();
      map = await initialize();
      requestAnimationFrame(() => map?.resize());
      map.once("load", () => {
        clearTimeout(timeout);
        map.resize();
      });
      map.on("error", () => { clearTimeout(timeout); showError(); });
    } catch (error) {
      clearTimeout(timeout);
      showError();
    }
  };
  const isDesktop = window.matchMedia?.("(min-width: 901px)").matches;
  if (isDesktop) {
    requestAnimationFrame(start);
  } else if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        start();
      }
    });
    observer.observe(mapRoot);
  } else {
    const button = document.createElement("button");
    button.textContent = "Загрузить карту";
    button.type = "button";
    button.addEventListener("click", start, { once: true });
    mapContainer.appendChild(button);
  }
  async function initialize() {
    const cards = Array.from(document.querySelectorAll("[data-city-card]"));
    const points = cards.map((card) => ({
      lat: parseFloat(card.dataset.lat),
      lng: parseFloat(card.dataset.lng),
      name: card.dataset.name,
      slug: card.dataset.slug,
      thumb: card.dataset.thumb,
      count: parseInt(card.dataset.count || "0", 10),
    }));

    const cityMap = await window.OpenFreeMap.create(mapContainer, {
      center: [0, 20],
      zoom: 1.5,
      navigationPosition: "top-right",
    });

    const bounds = new maplibregl.LngLatBounds();

    points.forEach((point) => {
      if (!Number.isFinite(point.lat) || !Number.isFinite(point.lng) || Math.abs(point.lat) > 90 || Math.abs(point.lng) > 180) {
        return;
      }

      const markerEl = document.createElement("button");
      markerEl.type = "button";
      markerEl.className = point.thumb ? "map-pin" : "map-pin map-pin--empty";
      markerEl.setAttribute("aria-label", point.name);
      if (point.thumb) {
        const image = document.createElement("img");
        image.src = point.thumb;
        image.alt = point.name;
        markerEl.appendChild(image);
      }
      const count = document.createElement("span");
      count.textContent = String(point.count);
      markerEl.appendChild(count);
      markerEl.addEventListener("click", () => {
        window.dispatchEvent(new CustomEvent("city:open", { detail: { slug: point.slug } }));
      });

      new maplibregl.Marker({ element: markerEl }).setLngLat([point.lng, point.lat]).addTo(cityMap);
      bounds.extend([point.lng, point.lat]);
    });

    if (!bounds.isEmpty()) {
      window.OpenFreeMap.fitBounds(cityMap, bounds, { padding: 56, maxZoom: 10, duration: 0 });
    }
    return cityMap;
  }
})();
