// Тема интерфейса: выбор пользователя в localStorage, иначе — системная настройка.
// Начальная тема ставится ещё в index.html, чтобы страница не мигала при загрузке.
const KEY = 'aihr-theme';

export function currentTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

export function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // приватный режим или запрет хранилища — тема просто не запомнится
  }
}
