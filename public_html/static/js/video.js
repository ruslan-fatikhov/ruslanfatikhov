document.querySelectorAll('[data-vimeo]').forEach((button) => {
  button.addEventListener('click', () => {
    const id = button.dataset.vimeo;
    if (!/^\d+$/.test(id)) return;
    const iframe = document.createElement('iframe');
    iframe.src = `https://player.vimeo.com/video/${id}?autoplay=1`;
    iframe.title = 'TimeBox Profile UI';
    iframe.allow = 'autoplay; fullscreen; picture-in-picture';
    iframe.allowFullscreen = true;
    iframe.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;border:0';
    button.replaceWith(iframe);
  }, { once: true });
});
