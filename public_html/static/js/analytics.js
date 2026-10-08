(() => {
  const load = () => {
    const initialize = () => {
      window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
      window.ym.l = Date.now();
      const script = document.createElement('script');
      script.async = true;
      script.src = 'https://mc.yandex.ru/metrika/tag.js?id=107065191';
      document.body.appendChild(script);
      window.ym(107065191, 'init', { ssr: true, webvisor: true, clickmap: true, ecommerce: 'dataLayer', referrer: document.referrer, url: location.href, accurateTrackBounce: true, trackLinks: true });
    };
    if ('requestIdleCallback' in window) window.requestIdleCallback(initialize, { timeout: 3000 });
    else setTimeout(initialize, 1000);
  };
  if (document.readyState === 'complete') load();
  else window.addEventListener('load', load, { once: true });
})();
