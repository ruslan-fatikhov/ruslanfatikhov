(() => {
  const stack = [];
  const focusable = (node) => [...node.querySelectorAll('button, a[href], input, select, textarea, [tabindex="0"]')]
    .filter((item) => !item.disabled && item.getClientRects().length && !item.closest('[inert]'));
  const open = (node) => {
    if (!node || stack.some((entry) => entry.node === node)) return;
    const entry = { node, previous: document.activeElement, inert: [], released: [], overflow: document.body.style.overflow };
    for (let ancestor = node; ancestor; ancestor = ancestor.parentElement) {
      if (ancestor.inert) { ancestor.inert = false; entry.released.push(ancestor); }
    }
    // Disable siblings along the ancestor path, including an underlying dialog.
    for (let child = node; child.parentElement && child !== document.body; child = child.parentElement) {
      for (const sibling of child.parentElement.children) {
        if (sibling !== child && !sibling.inert && !['SCRIPT', 'STYLE'].includes(sibling.tagName)) {
          sibling.inert = true;
          entry.inert.push(sibling);
        }
      }
    }
    entry.role = node.getAttribute('role');
    entry.modal = node.getAttribute('aria-modal');
    node.setAttribute('role', 'dialog');
    node.setAttribute('aria-modal', 'true');
    node.tabIndex = -1;
    stack.push(entry);
    document.body.style.overflow = 'hidden';
    (focusable(node)[0] || node).focus();
  };
  const close = (node) => {
    const index = stack.findIndex((entry) => entry.node === node);
    if (index < 0) return;
    while (stack.length > index) {
      const entry = stack.pop();
      entry.inert.forEach((sibling) => { sibling.inert = false; });
      if (entry.role === null) entry.node.removeAttribute('role'); else entry.node.setAttribute('role', entry.role);
      if (entry.modal === null) entry.node.removeAttribute('aria-modal'); else entry.node.setAttribute('aria-modal', entry.modal);
      entry.released.forEach((ancestor) => { ancestor.inert = true; });
      document.body.style.overflow = entry.overflow;
      const previous = entry.previous?.isConnected && entry.previous !== document.body
        ? entry.previous : document.querySelector('main a[href], header a[href]');
      previous?.focus();
    }
  };
  document.addEventListener('keydown', (event) => {
    const entry = stack.at(-1);
    if (!entry || event.key !== 'Tab') return;
    const nodes = focusable(entry.node);
    const current = nodes.indexOf(document.activeElement);
    event.preventDefault();
    if (!nodes.length) { entry.node.focus(); return; }
    nodes[(current + (event.shiftKey ? -1 : 1) + nodes.length) % nodes.length].focus();
  });
  document.addEventListener('focusin', (event) => {
    const entry = stack.at(-1);
    if (entry && !entry.node.contains(event.target)) (focusable(entry.node)[0] || entry.node).focus();
  });
  window.siteDialogs = { open, close };
})();
