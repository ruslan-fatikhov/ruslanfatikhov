window.MountainsPeaksLayer = (() => {
  let markers = [];

  function popupHtml(peak) {
    const elevation = peak.elevation === null || peak.elevation === undefined ? "" : `<p>${Math.round(peak.elevation)} м</p>`;
    const date = peak.summitedAt ? `<p>${peak.summitedAt}</p>` : "";
    return `<div class="mountains__popup"><h2>${escapeHtml(peak.name)}</h2>${elevation}${date}</div>`;
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

  function update(map, peaks) {
    markers.forEach((marker) => marker.remove());
    markers = [];
    peaks.filter((peak) => peak.isSummited).forEach((peak) => {
      const lat = Number(peak.latitude);
      const lng = Number(peak.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return;
      }
      const element = document.createElement("button");
      element.type = "button";
      element.className = "mountains__peak-marker";
      element.setAttribute("aria-label", peak.name);
      const popup = new maplibregl.Popup({ offset: 18 }).setHTML(popupHtml(peak));
      const marker = new maplibregl.Marker({ element }).setLngLat([lng, lat]).setPopup(popup).addTo(map);
      markers.push(marker);
    });
  }

  function destroy() {
    markers.forEach((marker) => marker.remove());
    markers = [];
  }

  return { update, destroy };
})();
