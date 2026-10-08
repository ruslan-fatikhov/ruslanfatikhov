window.MountainsGpxLayer = (() => {
  const sourceIds = new Set();
  const clickHandlers = new Map();

  function sourceId(route) {
    return `gpx-source-${route.id}`;
  }

  function layerId(route) {
    return `gpx-line-${route.id}`;
  }

  function update(map, routes) {
    routes.forEach((route, index) => {
      const sid = sourceId(route);
      const lid = layerId(route);
      const data = route.geojson || { type: "FeatureCollection", features: [] };
      if (map.getSource(sid)) {
        map.getSource(sid).setData(data);
      } else {
        map.addSource(sid, { type: "geojson", data });
        sourceIds.add(sid);
      }
      if (!map.getLayer(lid)) {
        map.addLayer({
          id: lid,
          type: "line",
          source: sid,
          paint: {
            "line-color": routeColor(index),
            "line-width": 4,
            "line-opacity": 0.86,
          },
          layout: {
            "line-cap": "round",
            "line-join": "round",
          },
        });
        const handler = (event) => {
          const coordinates = event.lngLat;
          new maplibregl.Popup()
            .setLngLat(coordinates)
            .setHTML(`<strong>${escapeHtml(route.name)}</strong>`)
            .addTo(map);
        };
        map.on("click", lid, handler);
        clickHandlers.set(lid, handler);
      }
    });
  }

  function setVisible(map, routeId, visible) {
    const lid = `gpx-line-${routeId}`;
    if (map.getLayer(lid)) {
      map.setLayoutProperty(lid, "visibility", visible ? "visible" : "none");
    }
  }

  function destroy(map) {
    clickHandlers.forEach((handler, lid) => {
      if (map.getLayer(lid)) {
        map.off("click", lid, handler);
        map.removeLayer(lid);
      }
    });
    clickHandlers.clear();
    sourceIds.forEach((sid) => {
      if (map.getSource(sid)) {
        map.removeSource(sid);
      }
    });
    sourceIds.clear();
  }

  function routeColor(index) {
    return ["#1976d2", "#2e7d32", "#c2410c", "#7b1fa2", "#00838f"][index % 5];
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[char]));
  }

  return { update, setVisible, destroy };
})();
