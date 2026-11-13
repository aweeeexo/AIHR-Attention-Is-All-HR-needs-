import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft, ArrowRight, ChartNoAxesColumnIncreasing,
  FilePlus2, LoaderCircle, RefreshCw,
} from 'lucide-react';
import '@fontsource-variable/inter';
import './style.css';
import { createApi } from './api.js';
import { Upload } from './upload.jsx';
import { Batch, Match, Notices } from './results.jsx';

const api = createApi(import.meta.env.VITE_API_URL || 'http://localhost:8000');
const steps = ['Обезличивание', 'Извлечение требований', 'Сопоставление', 'Расчёт баллов', 'Отчёт'];

function readLocation() {
  const [, kind, id, vacancy] = window.location.hash.split('/');
  return ['runs', 'batches'].includes(kind) && id ? { kind, id, vacancy } : null;
}

function path(kind, id, vacancy) {
  return `#/${kind}/${encodeURIComponent(id)}${vacancy ? '/' + encodeURIComponent(vacancy) : ''}`;
}

function App() {
  const [mode, setMode] = useState('single');
  const [health, setHealth] = useState(undefined);
  const [exampleFiles, setExampleFiles] = useState(null);
  const [route, setRoute] = useState(readLocation);
  const [record, setRecord] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const cache = useRef(new Map());
  const busy = useRef(false);
  const recordKey = route && `${route.kind}/${route.id}`;

  async function checkConnection() {
    setHealth(undefined);
    const [status, files] = await Promise.allSettled([api.health(), api.files()]);
    setHealth(status.status === 'fulfilled' ? status.value : null);
    setExampleFiles(files.status === 'fulfilled' ? files.value : null);
  }

  useEffect(() => {
    checkConnection();
    const navigate = () => {
      setError('');
      setRoute(readLocation());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  useEffect(() => {
    if (!recordKey) return undefined;
    let active = true;
    const [kind, id] = recordKey.split('/');
    const stored = cache.current.get(recordKey);
    if (stored) {
      setRecord({ key: recordKey, value: stored });
    } else {
      const load = kind === 'runs' ? api.run : api.batch;
      Promise.resolve().then(() => load(decodeURIComponent(id))).then((value) => {
        if (!active) return;
        cache.current.set(recordKey, value);
        setRecord({ key: recordKey, value });
      }).catch((failure) => {
        if (active) setRecord({ key: recordKey, error: failure.message });
      });
    }
    return () => { active = false; };
  }, [recordKey]);

  async function analyze(request) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError('');
    try {
      const value = await request();
      const next = value.batch_id ? path('batches', value.batch_id) : path('runs', value.run_id);
      cache.current.set(next.slice(2), value);
      window.location.hash = next;
    } catch (failure) {
      setError(failure.message);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  const current = record?.key === recordKey ? record : null;
  const result = current?.value;
  const batch = route?.kind === 'batches';
  const vacancy = result && !batch && result.vacancies.find(({ id }) => encodeURIComponent(id) === route.vacancy);
  const initial = !route;
  const modelStatus = health ? (health.llm === 'configured' ? 'LLM подключена' : 'Без LLM')
    : health === null ? 'API недоступен' : 'Проверяем API';
  const retrieval = health && (health.retrieval === 'bm25+embeddings' ? 'BM25 + эмбеддинги' : 'BM25');

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="AIHR · Новый анализ">
          <strong>AIHR</strong>
        </a>
        <nav aria-label="Рабочая область">
          <a className={initial ? 'active' : ''} href="#/" aria-current={initial ? 'page' : undefined}>
            <FilePlus2 size={16} aria-hidden="true" /> Новый анализ
          </a>
          {route && (
            <a className="active" href={`#/${recordKey}`} aria-current={vacancy ? undefined : 'page'}>
              <ChartNoAxesColumnIncreasing size={17} aria-hidden="true" /> {batch ? 'Матрица кандидатов' : 'Результат анализа'}
            </a>
          )}
        </nav>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            {vacancy
              ? <a className="back" href={`#/${recordKey}`}><ArrowLeft size={15} aria-hidden="true" /> К рейтингу вакансий</a>
              : <strong>{initial ? 'Новый анализ' : batch ? 'Пакет резюме' : 'Результат анализа'}</strong>}
          </div>
          <button className="connection" onClick={checkConnection} title="Обновить состояние API"
            aria-label={['Проверить состояние API', modelStatus, retrieval].filter(Boolean).join('. ')}>
            <span className={`dot ${health?.status === 'ok' ? 'online' : health === null ? 'offline' : ''}`} />
            <span>{modelStatus}</span>
            {retrieval && <span className="retrieval">{retrieval}</span>}
            <RefreshCw size={13} aria-hidden="true" />
          </button>
        </header>

        <main className="content" id="main">
          {initial ? (
            <div className="analysis-form">
              <div className="page-intro">
                <h1>Сопоставление резюме с вакансиями</h1>
              </div>
              <div className="analysis-layout">
                <div>
                  <div className="mode-control" role="group" aria-label="Режим анализа">
                    <button type="button" aria-pressed={mode === 'single'} disabled={pending} onClick={() => setMode('single')}>Одно резюме</button>
                    <button type="button" aria-pressed={mode === 'batch'} disabled={pending} onClick={() => setMode('batch')}>Пакет резюме</button>
                  </div>
                  <Upload mode={mode} pending={pending} submit={(resumes, vacancies) => analyze(() => api.upload(mode, resumes, vacancies))} />
                  <Notices error={error} />
                  {pending && (
                    <section className="progress" role="status">
                      <LoaderCircle className="spin" size={20} aria-hidden="true" />
                      <div><strong>Анализируем документы</strong><p>С LLM ответ может занять несколько минут.</p><p>{steps.join(' → ')}</p></div>
                    </section>
                  )}
                </div>
                <Example mode={mode} files={exampleFiles} pending={pending} run={(resume) => analyze(() => api.example(mode, resume))} />
              </div>
            </div>
          ) : (
            <>
              <Notices error={current?.error} />
              {!current && <div className="progress" role="status"><LoaderCircle className="spin" size={21} aria-hidden="true" /> Загружаем результат…</div>}
              {result && (batch
                ? <Batch result={result} runUrl={(id) => path('runs', id)} />
                : <Match result={result} vacancy={vacancy} api={api} reportUrl={(id) => path('runs', result.run_id, id)} />)}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function Example({ mode, files, pending, run }) {
  const [resume, setResume] = useState('');
  return (
    <section className="example" aria-labelledby="example-title">
      <h2 id="example-title">Пример из кейса</h2>
      <p>{mode === 'batch' ? 'Все резюме и вакансии из кейса МФТИ.' : 'Резюме и вакансии из кейса МФТИ.'}</p>
      <div className="example-actions">
        {mode === 'single' && Boolean(files?.resumes.length) && (
          <select aria-label="Резюме из кейса" value={files.resumes.includes(resume) ? resume : ''} onChange={(event) => setResume(event.target.value)} disabled={pending}>
            <option value="">Первое резюме</option>
            {files.resumes.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        )}
        <button className="button secondary" disabled={pending} onClick={() => run(files?.resumes.includes(resume) ? resume : '')}>Запустить пример <ArrowRight size={17} /></button>
      </div>
    </section>
  );
}

createRoot(document.getElementById('root')).render(<App />);
