const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = (file) => fs.readFileSync(`static/js/${file}.js`, 'utf8');
class Element {
  constructor() { this.handlers = {}; this.children = []; this.dataset = {}; this.hidden = false; this.value = ''; this.textContent = ''; }
  addEventListener(type, callback) { this.handlers[type] = callback; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; this.textContent = ''; }
  set innerHTML(value) { this.replaceChildren(); }
  focus() {}
  setAttribute(name, value) { this[name] = value; }
}
function searchFixture(fetch) {
  const selectors = ["[data-action='open-search']", "[data-action='close-search']", '[data-search]', '[data-search-input]', '[data-search-results]'];
  const nodes = Object.fromEntries(selectors.map((s) => [s, new Element()]));
  const document = { querySelector: (s) => nodes[s], documentElement: { dataset: { lang: 'ru' } }, createElement: () => new Element(), createDocumentFragment: () => new Element(), addEventListener() {} };
  vm.runInNewContext(source('search'), { document, fetch, window: { siteDialogs: { open() {}, close() {} } } });
  return { input: nodes[selectors[3]], results: nodes[selectors[4]], close: nodes[selectors[1]] };
}
test('search shares in-flight fetch and ignores stale results', async () => {
  let calls = 0, resolve;
  const f = searchFixture(() => { calls++; return new Promise((r) => { resolve = r; }); });
  const first = f.input.handlers.input({ target: { value: 'old' } });
  const second = f.input.handlers.input({ target: { value: 'new' } });
  assert.equal(calls, 1);
  resolve({ ok: true, json: async () => [{ slug: 'new', headline: { ru: 'new' } }] });
  await Promise.all([first, second]);
  assert.equal(f.results.children.length, 1);
  assert.equal(f.results.children[0].children[0].href, '/new?lang=ru');
});
test('search handles errors and permits retry', async () => {
  let calls = 0;
  const f = searchFixture(async () => { calls++; return { ok: false, status: 503 }; });
  await f.input.handlers.input({ target: { value: 'test' } });
  assert.match(f.results.textContent, /Не удалось/);
  await f.input.handlers.input({ target: { value: 'test2' } });
  assert.equal(calls, 2);
});
test('clearing and closing search invalidates pending render', async () => {
  let resolve;
  const f = searchFixture(() => new Promise((r) => { resolve = r; }));
  const pending = f.input.handlers.input({ target: { value: 'test' } });
  await f.input.handlers.input({ target: { value: '' } });
  f.close.handlers.click();
  resolve({ ok: true, json: async () => [{ slug: 'test', headline: { ru: 'test' } }] });
  await pending;
  assert.equal(f.results.children.length, 0);
});
test('Vimeo iframe is created only after a click', () => {
  const button = new Element(); button.dataset.vimeo = '593696263';
  let replaced, created = 0;
  button.replaceWith = (node) => { replaced = node; };
  vm.runInNewContext(source('video'), { document: { querySelectorAll: () => [button], createElement: (tag) => { assert.equal(tag, 'iframe'); created++; return { style: {} }; } } });
  assert.equal(created, 0);
  button.handlers.click();
  assert.equal(created, 1);
  assert.match(replaced.src, /593696263\?autoplay=1$/);
});
test('version changes never reload or clear caches', () => {
  const fail = () => { throw new Error('Unexpected version side effect'); };
  vm.runInNewContext(source('version-check'), { window: { location: { reload: fail }, caches: { delete: fail } } });
});
test('MapLibre is not requested before map intersects viewport', async () => {
  let intersect;
  const container = new Element(), root = new Element(), head = new Element();
  const nodes = { 'link[href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css"]': null };
  const observer = class { constructor(callback) { intersect = callback; } observe() {} disconnect() {} };
  const document = {
    getElementById: () => container,
    querySelector: (selector) => (selector in nodes ? nodes[selector] : root),
    querySelectorAll: () => [],
    createElement: () => new Element(),
    head,
  };
  const window = { IntersectionObserver: observer, matchMedia: () => ({ matches: false }) };
  const context = { document, window, IntersectionObserver: observer, setTimeout: () => 1, clearTimeout() {}, requestAnimationFrame: (callback) => callback() };
  vm.runInNewContext(`${source('maplibre-openfreemap')}\n${source('map')}`, context);
  assert.equal(head.children.length, 0);
  intersect([{ isIntersecting: false }]);
  assert.equal(head.children.length, 0);
  intersect([{ isIntersecting: true }]);
  assert.equal(head.children.length, 2);
  head.children[1].onerror(new Error('network'));
  assert.equal(head.children.length, 3);
  head.children[2].onerror(new Error('network'));
  await new Promise(setImmediate);
  assert.match(container.children[0].textContent, /Не удалось загрузить карту/);
});
