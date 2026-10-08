(() => {
  // The server resolves URL/cookie preferences and available translations.
  const lang = document.documentElement.lang;
  document.cookie = `lang=${encodeURIComponent(lang)}; path=/; max-age=31536000; SameSite=Lax`;
  document.querySelectorAll('button[data-lang]').forEach((button) => {
    button.dataset.active = String(button.dataset.lang === lang);
    button.addEventListener('click', () => {
      const url = new URL(location.href);
      url.searchParams.set('lang', button.dataset.lang);
      location.assign(url);
    });
  });
})();
