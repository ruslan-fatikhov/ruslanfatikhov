(() => {
  const container = document.getElementById("mountains-map");
  const stats = document.querySelector("[data-mountains-stats]");
  const routesList = document.querySelector("[data-mountains-routes]");
  const emptyState = document.querySelector("[data-mountains-empty]");
  if (!container || !window.OpenFreeMap || !window.MountainsData) {
    return;
  }

  let map;

  function renderSidebar(data) {
    const peaks = data.peaks || [];
    const routes = data.routes || [];
    if (stats) {
      stats.replaceChildren();
      const peaksStat = document.createElement("span");
      peaksStat.textContent = `Вершин: ${peaks.length}`;
      const routesStat = document.createElement("span");
      routesStat.textContent = `Маршрутов: ${routes.length}`;
      stats.append(peaksStat, routesStat);
    }
    if (emptyState) {
      emptyState.hidden = peaks.length > 0 || routes.length > 0;
    }
    if (!routesList) {
      return;
    }
    routesList.replaceChildren();
    routes.forEach((route) => {
      const row = document.createElement("div");
      row.className = "mountains__route";
      const name = document.createElement("strong");
      name.textContent = route.name;
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.textContent = "Скрыть";
      toggle.addEventListener("click", () => {
        const visible = toggle.dataset.visible !== "false";
        window.MountainsGpxLayer.setVisible(map, route.id, !visible);
        toggle.dataset.visible = String(!visible);
        toggle.textContent = visible ? "Показать" : "Скрыть";
      });
      const fit = document.createElement("button");
      fit.type = "button";
      fit.textContent = "К маршруту";
      fit.addEventListener("click", () => window.OpenFreeMap.fitBounds(map, route.bounds));
      row.append(name, toggle, fit);
      routesList.appendChild(row);
    });
  }

  async function start() {
    try {
      const data = await window.MountainsData.load();
      map = await window.OpenFreeMap.create(container, {
        center: [76.945, 43.2389],
        zoom: 10,
      });
      map.once("load", () => {
        window.MountainsPeaksLayer.update(map, data.peaks || []);
        window.MountainsGpxLayer.update(map, data.routes || []);
        renderSidebar(data);
      });
      window.addEventListener("beforeunload", () => {
        window.MountainsPeaksLayer.destroy();
        window.MountainsGpxLayer.destroy(map);
      });
    } catch (error) {
      container.replaceChildren();
      const message = document.createElement("div");
      message.className = "mountains__map-status";
      message.setAttribute("role", "status");
      message.textContent = "Не удалось загрузить карту горной активности.";
      container.appendChild(message);
    }
  }

  start();
})();
