import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Link as LinkIcon, Paperclip, Trash } from '@phosphor-icons/react';

const formats = /\.(docx|pdf|rtf|txt)$/i;
const sources = { file: 'Файл', url: 'По ссылке', example: 'Пример кейса' };

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
}

// D58: реестр открытых вакансий. Рекрутер добавляет вакансии один раз, дальше загружает только резюме
export function VacanciesPage({ api }) {
  const [items, setItems] = useState(undefined);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const input = useRef(null);
  const dialog = useRef(null);
  const [toDelete, setToDelete] = useState(null);

  // Удаление необратимо: сначала окно подтверждения «Да / Нет», фокус на безопасном «Нет»
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (toDelete && !node.open) node.showModal();
    if (!toDelete && node.open) node.close();
  }, [toDelete]);

  function confirmDelete() {
    const item = toDelete;
    setToDelete(null);
    if (item) act(async () => { await api.deleteVacancy(item.id); setNotice(`Вакансия «${item.title}» удалена.`); });
  }

  async function load() {
    try {
      setItems(await api.vacancies());
    } catch (failure) {
      setItems(null);
      setError(failure.message);
    }
  }

  useEffect(() => { load(); }, []);

  async function act(action) {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
      await load();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function addFiles(list) {
    const files = Array.from(list || []);
    const valid = files.filter((file) => formats.test(file.name));
    if (!valid.length) {
      setError('Поддерживаются только DOCX, PDF, RTF и TXT.');
      return;
    }
    act(async () => {
      const { added, errors } = await api.addVacancies(valid);
      const skipped = files.length - valid.length;
      setNotice(`Добавлено вакансий: ${added.length}.${skipped ? ` Пропущено файлов другого формата: ${skipped}.` : ''}`);
      if (errors.length) setError(errors.join(' · '));
    });
  }

  function addUrl(event) {
    event.preventDefault();
    const value = url.trim();
    if (!/^https?:\/\/\S+$/i.test(value)) {
      setError('Вставьте ссылку целиком, например https://hh.ru/vacancy/123456.');
      return;
    }
    act(async () => {
      const item = await api.addVacancyUrl(value);
      setUrl('');
      setNotice(`Добавлена вакансия «${item.title}».`);
    });
  }

  return (
    <div className="container page">
      <header className="page-head">
        <h1 className="heading-4">Открытые вакансии</h1>
        <p className="body-3 secondary">Добавьте вакансии один раз. Дальше на анализ достаточно загрузить резюме: система сравнит его со всеми вакансиями из списка.</p>
      </header>
      <div className="registry-layout">
        <section className="card registry-add" aria-labelledby="add-title">
          <h2 id="add-title" className="title-2">Добавить вакансию</h2>
          <form className="url-form" onSubmit={addUrl}>
            <label className="field">
              <span className="caption-1">Ссылка на вакансию</span>
              <input className="text-input body-6" type="url" inputMode="url" value={url} disabled={busy}
                placeholder="https://hh.ru/vacancy/123456" onChange={(event) => setUrl(event.target.value)} />
            </label>
            <button className="button secondary button-md" type="submit" disabled={busy || !url.trim()}>
              <LinkIcon size={16} aria-hidden="true" /> {busy ? 'Загружаем' : 'Добавить по ссылке'}
            </button>
            <p className="caption-2 secondary">hh.ru, сайт работодателя или любая открытая страница. Скачивается только текст вакансии, резюме никуда не уходит.</p>
          </form>
          <input hidden ref={input} type="file" accept=".docx,.pdf,.rtf,.txt" multiple aria-label="Файлы вакансий"
            onChange={(event) => { addFiles(event.target.files); event.target.value = ''; }} />
          <button className="dropzone" type="button" disabled={busy} onClick={() => input.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); addFiles(event.dataTransfer.files); }}>
            <Paperclip size={17} aria-hidden="true" />
            <span><strong>Выбрать файлы</strong><span className="drop-instruction"> или перетащите сюда</span><small>DOCX, PDF, RTF, TXT</small></span>
          </button>
          {notice && <p className="caption-2 ok-text" role="status">{notice}</p>}
          {error && <p className="caption-2 error-text" role="alert">{error}</p>}
        </section>

        <section className="card registry-list" aria-labelledby="list-title" aria-busy={items === undefined || busy}>
          <div className="registry-list-head">
            <h2 id="list-title" className="title-2">В списке{items?.length ? ` · ${items.length}` : ''}</h2>
            {Boolean(items?.length) && <a className="button primary button-sm" href="#/app">Загрузить резюме <ArrowRight size={16} aria-hidden="true" /></a>}
          </div>
          {items === undefined && <div className="registry-skeleton" aria-hidden="true">{[0, 1, 2].map((key) => <span className="skeleton" key={key} />)}</div>}
          {items === null && <p className="body-6 secondary">Список недоступен: API не отвечает. Проверьте, что сервер запущен.</p>}
          {items?.length === 0 && <div className="registry-empty"><p className="title-3">Вакансий пока нет</p><p className="body-6 secondary">Добавьте первую ссылкой или файлом слева.</p></div>}
          {Boolean(items?.length) && (
            <ul className="registry-items">
              {items.map((item) => (
                <li key={item.id}>
                  <div>
                    <p className="title-4">{item.title}</p>
                    <p className="caption-5 secondary">{[sources[item.source] || item.source, item.filename, formatDate(item.added_at)].filter(Boolean).join(' · ')}</p>
                    {item.url && <a className="caption-5 registry-url" href={item.url} target="_blank" rel="noreferrer noopener">{item.url}</a>}
                  </div>
                  <button type="button" className="icon-button" disabled={busy} aria-label={`Удалить вакансию «${item.title}»`}
                    onClick={() => setToDelete(item)}>
                    <Trash size={16} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <dialog ref={dialog} className="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-text"
        onClose={() => setToDelete(null)}>
        <h2 id="confirm-title" className="title-2">Удалить вакансию?</h2>
        <p id="confirm-text" className="body-6">
          Вакансия «{toDelete?.title}» будет удалена из списка открытых вакансий безвозвратно. Вернуть её можно только повторной загрузкой.
        </p>
        <div className="confirm-actions">
          <button type="button" className="button secondary button-md" autoFocus onClick={() => setToDelete(null)}>Нет</button>
          <button type="button" className="button danger button-md" onClick={confirmDelete}>Да, удалить</button>
        </div>
      </dialog>
    </div>
  );
}

// Источник «Открытые вакансии» в форме анализа
export function RegistrySummary({ registry }) {
  if (registry === undefined) return <div className="registry-skeleton" aria-hidden="true"><span className="skeleton" /></div>;
  if (!registry?.length) {
    return <p className="body-6 secondary">В списке открытых вакансий пусто. <a href="#/vacancies">Добавить вакансии</a></p>;
  }
  return (
    <div className="registry-summary">
      <p className="body-6">Резюме сравним со всеми открытыми вакансиями: {registry.length}.</p>
      <ul className="file-list">
        {registry.slice(0, 5).map((item) => <li key={item.id}><span>{item.title}</span></li>)}
      </ul>
      {registry.length > 5 && <p className="caption-2 secondary">И ещё {registry.length - 5}.</p>}
      <a className="caption-1" href="#/vacancies">Изменить список вакансий</a>
    </div>
  );
}
