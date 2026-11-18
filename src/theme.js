export const THEME_KEY = 'grab-theme';

const THEME_COLORS = {
  light: '#f4f0e7',
  dark: '#191917',
};

export function readThemePreference(storage = window.localStorage) {
  try {
    const saved = storage.getItem(THEME_KEY);
    return ['system', 'light', 'dark'].includes(saved) ? saved : 'system';
  } catch {
    return 'system';
  }
}

export function persistThemePreference(preference, storage = window.localStorage) {
  try {
    storage.setItem(THEME_KEY, preference);
  } catch {
    // Storage can be disabled; the current page theme still works.
  }
}

export function resolveTheme(preference, systemDark) {
  return preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;
}

export function applyTheme(
  preference,
  {
    systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches,
    root = document.documentElement,
    themeColor = document.querySelector('meta[name="theme-color"]'),
  } = {},
) {
  const theme = resolveTheme(preference, systemDark);
  root.dataset.theme = theme;
  if (themeColor) themeColor.setAttribute('content', THEME_COLORS[theme]);
  return theme;
}

export function watchSystemTheme(preference, onChange, media = window.matchMedia('(prefers-color-scheme: dark)')) {
  if (preference !== 'system') return () => {};
  const listener = () => onChange(media.matches);
  if (media.addEventListener) media.addEventListener('change', listener);
  else media.addListener(listener);
  return () => {
    if (media.removeEventListener) media.removeEventListener('change', listener);
    else media.removeListener(listener);
  };
}
