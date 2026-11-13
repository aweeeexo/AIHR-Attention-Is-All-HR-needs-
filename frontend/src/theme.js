// Тема: «системная» (по умолчанию), «светлая» или «тёмная». Выбор хранится в localStorage.
// Начальная тема ставится ещё в index.html, чтобы страница не мигала при загрузке.
const KEY = 'aihr-theme';
const media = () => window.matchMedia?.('(prefers-color-scheme: dark)');

export function storedMode() {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

function resolve(mode) {
  if (mode === 'light' || mode === 'dark') return mode;
  return media()?.matches ? 'dark' : 'light';
}

export function applyMode(mode) {
  document.documentElement.dataset.theme = resolve(mode);
  try {
    if (mode === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, mode);
  } catch {
    // хранилище недоступно — выбор просто не запомнится
  }
}

// Системная тема поменялась (например, вечером) — следуем за ней, если пользователь не выбрал свою
export function followSystem() {
  const query = media();
  const onChange = () => { if (storedMode() === 'system') applyMode('system'); };
  query?.addEventListener?.('change', onChange);
  return () => query?.removeEventListener?.('change', onChange);
}
