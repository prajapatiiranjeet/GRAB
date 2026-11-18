import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { applyTheme, persistThemePreference, readThemePreference, resolveTheme, watchSystemTheme } from '../src/theme.js';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test('new visitors default to the live system preference', () => {
  const storage = memoryStorage();
  assert.equal(readThemePreference(storage), 'system');
  assert.equal(resolveTheme('system', false), 'light');
  assert.equal(resolveTheme('system', true), 'dark');
});

test('manual theme choice persists and overrides system mode', () => {
  const storage = memoryStorage();
  persistThemePreference('dark', storage);
  assert.equal(readThemePreference(storage), 'dark');
  assert.equal(resolveTheme('dark', false), 'dark');
  assert.equal(resolveTheme('light', true), 'light');
});

test('applying a theme updates the document root and browser theme color', () => {
  const root = { dataset: {} };
  const attributes = {};
  const themeColor = { setAttribute: (name, value) => { attributes[name] = value; } };

  assert.equal(applyTheme('system', { systemDark: true, root, themeColor }), 'dark');
  assert.equal(root.dataset.theme, 'dark');
  assert.equal(attributes.content, '#191917');

  assert.equal(applyTheme('light', { systemDark: true, root, themeColor }), 'light');
  assert.equal(root.dataset.theme, 'light');
  assert.equal(attributes.content, '#f4f0e7');
});

test('System follows live OS changes while manual choices ignore them', () => {
  const listeners = new Set();
  const media = {
    matches: false,
    addEventListener: (_event, callback) => listeners.add(callback),
    removeEventListener: (_event, callback) => listeners.delete(callback),
  };
  const observed = [];
  const stop = watchSystemTheme('system', dark => observed.push(resolveTheme('system', dark)), media);

  media.matches = true;
  listeners.forEach(listener => listener());
  media.matches = false;
  listeners.forEach(listener => listener());
  assert.deepEqual(observed, ['dark', 'light']);
  stop();
  assert.equal(listeners.size, 0);

  let manualChangeCount = 0;
  watchSystemTheme('dark', () => manualChangeCount++, media);
  media.matches = true;
  listeners.forEach(listener => listener());
  assert.equal(manualChangeCount, 0);
  assert.equal(resolveTheme('dark', media.matches), 'dark');
});

test('the first-paint theme bootstrap runs in the document head', async () => {
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  assert.ok(html.indexOf('<script>') < html.indexOf('<body>'));
  assert.match(html, /prefers-color-scheme: dark/);
  assert.match(html, /localStorage\.getItem\('grab-theme'\)/);
});
