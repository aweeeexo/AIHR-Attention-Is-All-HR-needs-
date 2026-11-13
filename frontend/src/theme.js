// Тема: тёмная по умолчанию, светлая по выбору. Выбор хранится в localStorage.
// Начальная тема ставится ещё в index.html, чтобы страница не мигала при загрузке.
const KEY = 'aihr-theme';

export function storedMode() {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function applyMode(mode) {
  const theme = mode === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
  try {
    if (theme === 'dark') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // хранилище недоступно — выбор просто не запомнится
  }
}
