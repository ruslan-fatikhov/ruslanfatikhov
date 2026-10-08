(() => {
  const viewer = document.querySelector("[data-gallery-viewer]");
  const image = document.querySelector("[data-gallery-image]");
  const count = document.querySelector("[data-gallery-count]");
  const download = document.querySelector("[data-gallery-download]");
  const closeButtons = document.querySelectorAll("[data-gallery-close]");
  const nextButton = document.querySelector("[data-gallery-next]");
  const prevButton = document.querySelector("[data-gallery-prev]");

  if (!viewer || !image) {
    return;
  }

  const articleImages = Array.from(
    document.querySelectorAll("[data-article] .article__prose img")
  ).filter((img) => !img.closest("[data-vimeo]"));
  articleImages.forEach((img) => {
    img.tabIndex = 0;
    img.setAttribute('role', 'button');
    img.setAttribute('aria-label', `Открыть изображение: ${img.alt || 'Фото'}`);
    if (!img.dataset.full) {
      img.dataset.full = img.currentSrc || img.src;
    }
  });

  let items = [];
  let current = 0;

  const preload = (index) => {
    if (index < 0 || index >= items.length) {
      return;
    }
    const src = items[index].dataset.full;
    const img = new Image();
    img.src = src;
  };

  const show = (index) => {
    if (!items.length) {
      return;
    }
    current = index;
    const src = items[index].dataset.full;
    image.src = src;
    if (count) {
      count.textContent = `${index + 1} / ${items.length}`;
    }
    if (download) {
      download.href = src;
    }
    viewer.hidden = false;
    window.siteDialogs.open(viewer);
    preload(index - 1);
    preload(index + 1);
  };

  const close = () => {
    viewer.hidden = true;
    window.siteDialogs.close(viewer);
  };

  const next = () => {
    const nextIndex = (current + 1) % items.length;
    show(nextIndex);
  };

  const prev = () => {
    const prevIndex = (current - 1 + items.length) % items.length;
    show(prevIndex);
  };

  const openFromItem = (item) => {
    const gallery = item.closest("[data-gallery]");
    items = gallery
      ? Array.from(gallery.querySelectorAll("[data-full]"))
      : articleImages;
    const index = items.indexOf(item);
    if (index >= 0) {
      show(index);
    }
  };

  document.addEventListener("click", (event) => {
    const item = event.target.closest("[data-full]");
    if (!item || item.closest("[data-article] .article__prose")) {
      return;
    }
    event.preventDefault();
    openFromItem(item);
  });

  articleImages.forEach((img) => {
    img.addEventListener("click", () => openFromItem(img));
    img.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openFromItem(img);
      }
    });
  });

  closeButtons.forEach((button) => button.addEventListener("click", close));
  if (nextButton) {
    nextButton.addEventListener("click", next);
  }
  if (prevButton) {
    prevButton.addEventListener("click", prev);
  }

  document.addEventListener("keydown", (event) => {
    if (viewer.hidden) {
      return;
    }
    if (event.key === "Escape") {
      close();
    }
    if (event.key === "ArrowRight") {
      next();
    }
    if (event.key === "ArrowLeft") {
      prev();
    }
  });
})();
