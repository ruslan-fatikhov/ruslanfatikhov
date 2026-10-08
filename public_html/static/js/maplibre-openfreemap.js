window.OpenFreeMap = (() => {
  const LIBRE_CSS = "https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css";
  const LIBRE_JS = [
    "https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js",
    "https://cdn.jsdelivr.net/npm/maplibre-gl@5.6.0/dist/maplibre-gl.js",
  ];
  const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
  let loading;

  function loadCss() {
    if (document.querySelector(`link[href="${LIBRE_CSS}"]`)) {
      return;
    }
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = LIBRE_CSS;
    document.head.appendChild(css);
  }

  function loadScript(index, resolve, reject) {
    const script = document.createElement("script");
    script.src = LIBRE_JS[index];
    script.async = true;
    script.onload = resolve;
    script.onerror = () => {
      const nextIndex = index + 1;
      if (nextIndex < LIBRE_JS.length) {
        loadScript(nextIndex, resolve, reject);
      } else {
        reject(new Error("MapLibre failed to load"));
      }
    };
    document.head.appendChild(script);
  }

  function load() {
    if (window.maplibregl) {
      return Promise.resolve();
    }
    if (loading) {
      return loading;
    }
    loading = new Promise((resolve, reject) => {
      loadCss();
      loadScript(0, resolve, reject);
    });
    return loading;
  }

  async function create(container, options = {}) {
    await load();
    container.replaceChildren();
    const map = new maplibregl.Map({
      container,
      style: options.style || STYLE_URL,
      center: options.center || [76.945, 43.2389],
      zoom: options.zoom ?? 10,
    });
    if (options.navigationControl !== false) {
      map.addControl(new maplibregl.NavigationControl(), options.navigationPosition || "top-right");
    }
    return map;
  }

  function fitBounds(map, bounds, options = {}) {
    if (!map || !bounds || !bounds[0] || !bounds[1]) {
      return;
    }
    map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 700, ...options });
  }

  return { STYLE_URL, load, create, fitBounds };
})();
