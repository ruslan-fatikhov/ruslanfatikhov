(() => {
  const container = document.querySelector("[data-city-location-map]");
  const input = document.querySelector("[data-city-location-input]");
  const value = document.querySelector("[data-city-location-value]");

  if (!container || !input || !value) {
    return;
  }

  const fallback = { lat: 55.796127, lng: 49.106405 };
  let map;
  let marker;

  const parseLocation = (raw) => {
    const parts = String(raw || "").split(",").map((part) => part.trim());
    if (parts.length !== 2) {
      return null;
    }
    const lat = Number(parts[0]);
    const lng = Number(parts[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
      return null;
    }
    return { lat, lng };
  };

  const formatLocation = ({ lat, lng }) => `${lat.toFixed(6)}, ${lng.toFixed(6)}`;

  const setLocation = (location) => {
    input.value = formatLocation(location);
    value.textContent = input.value;
  };

  const placeMarker = (location) => {
    setLocation(location);
    if (!marker) {
      marker = new maplibregl.Marker({ draggable: true })
        .setLngLat([location.lng, location.lat])
        .addTo(map);
      marker.on("dragend", () => {
        const lngLat = marker.getLngLat();
        setLocation({ lat: lngLat.lat, lng: lngLat.lng });
      });
      return;
    }
    marker.setLngLat([location.lng, location.lat]);
  };

  const showError = () => {
    container.replaceChildren();
    const message = document.createElement("div");
    message.className = "admin-location-map__empty";
    message.setAttribute("role", "status");
    message.textContent = "Не удалось загрузить карту. Попробуйте обновить страницу.";
    container.appendChild(message);
  };

  const start = async () => {
    try {
      if (!window.OpenFreeMap) {
        throw new Error("Missing OpenFreeMap loader");
      }
      const initial = parseLocation(input.value);
      const center = initial || fallback;
      map = await window.OpenFreeMap.create(container, {
        center: [center.lng, center.lat],
        zoom: initial ? 10 : 4,
        navigationPosition: "top-right",
      });
      map.once("load", () => map.resize());
      map.on("click", (event) => {
        placeMarker({ lat: event.lngLat.lat, lng: event.lngLat.lng });
      });
      if (initial) {
        placeMarker(initial);
      }
    } catch (error) {
      showError();
    }
  };

  start();
})();
