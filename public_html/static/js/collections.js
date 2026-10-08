(() => {
  const page = document.querySelector("[data-collection-page]");
  const modal = document.querySelector("[data-collection-modal]");
  const dataNode = document.querySelector("#collection-items-data");

  if (!page || !modal || !dataNode) {
    return;
  }

  const baseUrl = page.dataset.collectionBaseUrl;
  const initialItemId = page.dataset.initialItemId;
  const collectionTitle = page.dataset.collectionTitle;
  const params = new URLSearchParams(window.location.search);
  params.set("lang", document.documentElement.lang);
  const suffix = `?${params}`;
  const itemUrl = (id) => `${baseUrl}${id ? '/' + encodeURIComponent(id) : ''}${suffix}`;
  const updateMetadata = (item) => {
    document.title = item ? `${item.title} | ${collectionTitle}` : `${collectionTitle} | Collections`;
    const canonical = new URL(itemUrl(item?.id), location.origin);
    canonical.search = new URLSearchParams({ lang: document.documentElement.lang });
    const url = canonical.href;
    document.querySelector('link[rel="canonical"]').href = url;
    document.querySelector('meta[property="og:url"]').content = url;
    for (const selector of ['meta[property="og:title"]', 'meta[name="twitter:title"]']) document.querySelector(selector).content = document.title;
    document.querySelectorAll('link[rel="alternate"]').forEach((link) => { link.href = url; });
  };

  let items = [];
  try {
    items = JSON.parse(dataNode.textContent || "[]");
  } catch (error) {
    console.error("Failed to parse collection item data", error);
    return;
  }

  const itemMap = new Map(items.map((item) => [item.id, item]));
  const titleNode = modal.querySelector("[data-collection-title]");
  const galleryNode = modal.querySelector("[data-collection-gallery]");
  const fieldsNode = modal.querySelector("[data-collection-fields]");
  const closeButtons = modal.querySelectorAll("[data-collection-close]");
  const viewer = document.querySelector("[data-gallery-viewer]");
  const viewerImage = document.querySelector("[data-gallery-image]");
  const viewerCount = document.querySelector("[data-gallery-count]");
  const viewerDownload = document.querySelector("[data-gallery-download]");
  const viewerCloseButtons = document.querySelectorAll("[data-gallery-close]");
  const viewerNextButton = document.querySelector("[data-gallery-next]");
  const viewerPrevButton = document.querySelector("[data-gallery-prev]");
  const initialPath = window.location.pathname.replace(/\/$/, "");

  let isOpen = false;
  let isNavigatingHistory = false;
  let currentGallery = [];
  let currentGalleryIndex = 0;

  const showViewer = (index) => {
    if (!viewer || !viewerImage || !currentGallery.length) {
      return;
    }

    currentGalleryIndex = index;
    const src = currentGallery[index];
    viewerImage.src = src;

    if (viewerCount) {
      viewerCount.textContent = `${index + 1} / ${currentGallery.length}`;
    }
    if (viewerDownload) {
      viewerDownload.href = src;
    }

    viewer.hidden = false;
    window.siteDialogs.open(viewer);
  };

  const closeViewer = () => {
    if (!viewer) {
      return;
    }
    viewer.hidden = true;
    window.siteDialogs.close(viewer);
  };

  const showNextViewerImage = () => {
    if (!currentGallery.length) {
      return;
    }
    showViewer((currentGalleryIndex + 1) % currentGallery.length);
  };

  const showPrevViewerImage = () => {
    if (!currentGallery.length) {
      return;
    }
    showViewer((currentGalleryIndex - 1 + currentGallery.length) % currentGallery.length);
  };

  const renderGallery = (gallery, title, thumbs = []) => {
    galleryNode.innerHTML = "";
    currentGallery = gallery || [];

    if (!currentGallery.length) {
      galleryNode.hidden = true;
      return;
    }

    currentGallery.forEach((src, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "collection-modal__gallery-item";
      item.addEventListener("click", () => showViewer(index));

      const image = document.createElement("img");
      image.src = thumbs[index] || src;
      image.alt = `${title} photo ${index + 1}`;
      image.loading = "lazy";
      image.decoding = "async";

      item.appendChild(image);
      galleryNode.appendChild(item);
    });

    galleryNode.hidden = false;
  };

  const renderFields = (fields) => {
    fieldsNode.innerHTML = "";
    if (!fields || !fields.length) {
      fieldsNode.hidden = true;
      return;
    }

    fields.forEach((field) => {
      const row = document.createElement("div");
      row.className = "collection-fields__row";

      const dt = document.createElement("dt");
      dt.textContent = field.label;

      const dd = document.createElement("dd");
      dd.textContent = field.value;

      row.append(dt, dd);
      fieldsNode.appendChild(row);
    });

    fieldsNode.hidden = false;
  };

  const renderItem = (item) => {
    titleNode.textContent = item.title || "";
    const gallery = item.gallery && item.gallery.length ? item.gallery : (item.image_path ? [item.image_path] : []);
    renderGallery(gallery, item.title || "", item.thumbnails || []);
    renderFields(item.fields || []);
  };

  const openModal = (itemId, pushHistory = true) => {
    const item = itemMap.get(itemId);
    if (!item) {
      return;
    }

    renderItem(item);
    modal.hidden = false;
    window.siteDialogs.open(modal);
    updateMetadata(item);
    requestAnimationFrame(() => {
      modal.classList.add("is-open");
    });

    isOpen = true;

    if (pushHistory) {
      window.history.pushState({ collectionModal: true, itemId }, "", itemUrl(itemId));
    }
  };

  const closeModal = (updateHistory = true) => {
    if (!isOpen) {
      return;
    }

    modal.classList.remove("is-open");

    isOpen = false;
    closeViewer();
    window.siteDialogs.close(modal);
    updateMetadata(null);

    window.setTimeout(() => {
      if (!isOpen) {
        modal.hidden = true;
      }
    }, 280);

    if (updateHistory && window.location.pathname !== baseUrl) {
      if (window.history.state && window.history.state.collectionModal) {
        isNavigatingHistory = true;
        window.history.back();
      } else if (initialPath !== baseUrl) {
        window.history.replaceState({}, "", itemUrl());
      } else {
        window.history.pushState({}, "", itemUrl());
      }
    }
  };

  document.querySelectorAll("[data-collection-item-trigger]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      openModal(link.dataset.itemId);
    });
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", () => closeModal());
  });

  document.addEventListener("keydown", (event) => {
    if (viewer && !viewer.hidden) {
      if (event.key === "Escape") {
        closeViewer();
      }
      if (event.key === "ArrowRight") {
        showNextViewerImage();
      }
      if (event.key === "ArrowLeft") {
        showPrevViewerImage();
      }
      return;
    }

    if (event.key === "Escape") {
      closeModal();
    }
  });

  viewerCloseButtons.forEach((button) => {
    button.addEventListener("click", closeViewer);
  });

  if (viewerNextButton) {
    viewerNextButton.addEventListener("click", showNextViewerImage);
  }

  if (viewerPrevButton) {
    viewerPrevButton.addEventListener("click", showPrevViewerImage);
  }

  window.addEventListener("popstate", () => {
    if (isNavigatingHistory) {
      isNavigatingHistory = false;
    }

    const currentPath = window.location.pathname.replace(/\/$/, "");
    const basePath = baseUrl.replace(/\/$/, "");

    if (currentPath === basePath) {
      closeModal(false);
      return;
    }

    const itemId = currentPath.startsWith(`${basePath}/`)
      ? currentPath.slice(basePath.length + 1)
      : "";

    if (itemId && itemMap.has(itemId)) {
      openModal(itemId, false);
    } else {
      closeModal(false);
    }
  });

  if (initialItemId && itemMap.has(initialItemId)) {
    openModal(initialItemId, false);
  }
})();
