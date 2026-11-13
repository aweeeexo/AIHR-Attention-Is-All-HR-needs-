// Резюме, выбранное на первом экране, для экрана анализа («Добавить свои вакансии»).
// Живёт только в памяти вкладки: файл никуда не сохраняется.
let pendingResume = null;

export function setPendingResume(file) {
  pendingResume = file;
}

export function takePendingResume() {
  const file = pendingResume;
  pendingResume = null;
  return file;
}
