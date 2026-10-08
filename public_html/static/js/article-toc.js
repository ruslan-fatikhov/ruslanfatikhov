(() => {
  const article = document.querySelector("[data-article]");
  const toc = document.querySelector("[data-article-toc]");
  const tocList = document.querySelector("[data-article-toc-list]");
  const prose = document.querySelector("[data-article-prose]");
  const tocToggle = document.querySelector("[data-article-toc-toggle]");
  const tocOverlay = document.querySelector("[data-article-toc-overlay]");
  const tocClose = document.querySelector("[data-article-toc-close]");

  if (!article || !toc || !tocList || !prose) {
    return;
  }

  const headings = Array.from(prose.querySelectorAll("h2, h3"));
  if (!headings.length) {
    return;
  }

  const slugify = (text) =>
    text
      .toLowerCase()
      .trim()
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .replace(/\s+/g, "-");

  const linksById = new Map();

  let activeId = "";
  let isTicking = false;
  let isTocInteractionActive = false;
  const mobileMq = window.matchMedia("(max-width: 900px)");

  const isMobile = () => mobileMq.matches;
  mobileMq.addEventListener("change", () => closeMobileToc());

  const closeMobileToc = () => {
    if (!toc) {
      return;
    }
    toc.dataset.open = "false";
    window.siteDialogs.close(toc);
    if (tocOverlay) {
      tocOverlay.dataset.open = "false";
      tocOverlay.hidden = true;
    }
    isTocInteractionActive = false;
  };

  const openMobileToc = () => {
    if (!toc) {
      return;
    }
    toc.dataset.open = "true";
    if (tocOverlay) {
      tocOverlay.hidden = false;
      tocOverlay.dataset.open = "true";
    }
    isTocInteractionActive = true;
    window.siteDialogs.open(toc);
  };

  const setActive = (id) => {
    if (!id || id === activeId) {
      return;
    }
    if (activeId && linksById.has(activeId)) {
      linksById.get(activeId).classList.remove("article-toc__link--active");
    }
    if (linksById.has(id)) {
      linksById.get(id).classList.add("article-toc__link--active");
      activeId = id;
    }
  };

  headings.forEach((heading, index) => {
    if (!heading.id) {
      const base = slugify(heading.textContent || "") || `section-${index + 1}`;
      let candidate = base;
      let suffix = 2;
      while (document.getElementById(candidate)) {
        candidate = `${base}-${suffix}`;
        suffix += 1;
      }
      heading.id = candidate;
    }

    const item = document.createElement("li");
    item.className = `article-toc__item article-toc__item--level-${heading.tagName.slice(1)}`;

    const link = document.createElement("a");
    link.className = "article-toc__link";
    link.href = `#${heading.id}`;
    link.textContent = (heading.textContent || "").trim();
    link.dataset.targetId = heading.id;

    link.addEventListener("click", (event) => {
      event.preventDefault();
      isTocInteractionActive = true;
      setActive(heading.id);

      const target = document.getElementById(heading.id);
      if (!target) {
        return;
      }

      const topOffset = 72;
      const top = target.getBoundingClientRect().top + window.scrollY - topOffset;
      window.scrollTo({ top, behavior: "smooth" });
      history.replaceState(null, "", `#${heading.id}`);
      if (isMobile()) {
        closeMobileToc();
      }
    });

    item.appendChild(link);
    tocList.appendChild(item);
    linksById.set(heading.id, link);
  });

  toc.hidden = false;
  if (tocToggle) {
    tocToggle.hidden = false;
  }

  const findActiveId = () => {
    const topOffset = 84;
    const marker = window.scrollY + topOffset;
    let current = headings[0].id;
    headings.forEach((heading) => {
      if (heading.offsetTop <= marker) {
        current = heading.id;
      }
    });
    return current;
  };

  const updateActive = () => {
    isTicking = false;
    setActive(findActiveId());
  };

  const onScroll = () => {
    if (!isTocInteractionActive) {
      return;
    }
    if (isTicking) {
      return;
    }
    isTicking = true;
    window.requestAnimationFrame(updateActive);
  };

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);

  toc.addEventListener("pointerenter", () => {
    isTocInteractionActive = true;
  });

  toc.addEventListener("pointerleave", () => {
    isTocInteractionActive = false;
  });

  toc.addEventListener("focusin", () => {
    isTocInteractionActive = true;
  });

  if (tocToggle) {
    tocToggle.addEventListener("click", openMobileToc);
  }
  if (tocClose) {
    tocClose.addEventListener("click", closeMobileToc);
  }
  if (tocOverlay) {
    tocOverlay.addEventListener("click", closeMobileToc);
  }

  document.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    if (!toc.contains(event.target)) {
      isTocInteractionActive = false;
    }
  });

  document.addEventListener("focusin", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    if (!toc.contains(event.target)) {
      isTocInteractionActive = false;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMobileToc();
    }
  });

  const hash = window.location.hash.slice(1);
  if (hash && linksById.has(hash)) {
    setActive(hash);
  } else {
    setActive(findActiveId());
  }
})();
