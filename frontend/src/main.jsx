import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft, ArrowRight, BookOpen, ChartNoAxesColumnIncreasing,
  Files, LayoutGrid, LoaderCircle, ScanLine, ShieldCheck, UserRound,
} from 'lucide-react';
import '@fontsource-variable/inter';
import './style.css';
import { createApi } from './api.js';
import { Upload } from './upload.jsx';
import { Batch, Match, Notices } from './results.jsx';

const api = createApi(import.meta.env.VITE_API_URL || 'http://localhost:8000');
const steps = ['Загрузка', 'Обезличивание', 'Извлечение', 'Сопоставление', 'Балл', 'Отчёт'];

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

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/" aria-label="AIHR · Новый анализ">
          <span className="brand-icon"><ScanLine size={22} aria-hidden="true" /></span>
          <span><strong>AIHR</strong><small>Подбор персонала</small></span>
        </a>
        <div className="side-label">Рабочая область</div>
        <nav aria-label="Рабочая область">
          <a className={initial ? 'active' : ''} href="#/" aria-current={initial ? 'page' : undefined}>
            <LayoutGrid size={17} aria-hidden="true" /> Новый анализ
          </a>
          {route && (
            <a className="active" href={`#/${recordKey}`} aria-current={vacancy ? undefined : 'page'}>
              <ChartNoAxesColumnIncreasing size={17} aria-hidden="true" /> {batch ? 'Матрица кандидатов' : 'Результат анализа'}
            </a>
          )}
        </nav>
        <div className="sidebar-foot"><ShieldCheck size={18} aria-hidden="true" /> Обезличивание перед LLM</div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb"><span>Рабочая область</span><span aria-hidden="true">/</span><strong>{initial ? 'Новый анализ' : batch ? 'Пакет резюме' : 'Результат анализа'}</strong></div>
          <button className="connection" onClick={checkConnection} aria-label="Проверить состояние API" title="Проверить соединение">
            <span className={`dot ${health?.status === 'ok' ? 'online' : health === null ? 'offline' : ''}`} />
            {health ? <><span>{health.llm === 'configured' ? 'LLM подключена' : 'Без LLM'}</span><span className="retrieval">{health.retrieval === 'bm25+embeddings' ? 'BM25 + эмбеддинги' : 'BM25'}</span></> : health === null ? 'API недоступен' : 'Проверяем API'}
          </button>
        </header>

        <main className="content" id="main">
          {initial ? (
            <>
              <div className="page-intro">
                <div className="page-icon"><ScanLine size={24} aria-hidden="true" /></div>
                <h1>Сопоставление резюме<br className="intro-break" /> с вакансиями</h1>
                <p>Загрузите документы, чтобы увидеть рейтинг вакансий и подтверждения из резюме по каждому требованию.</p>
              </div>
              <div className="mode-control" role="group" aria-label="Режим анализа">
                <button type="button" aria-pressed={mode === 'single'} disabled={pending} onClick={() => setMode('single')}><UserRound size={16} /> Одно резюме</button>
                <button type="button" aria-pressed={mode === 'batch'} disabled={pending} onClick={() => setMode('batch')}><Files size={16} /> Пакет резюме</button>
              </div>
              <Upload mode={mode} pending={pending} submit={(resumes, vacancies) => analyze(() => api.upload(mode, resumes, vacancies))} />
              <Notices error={error} />
              {pending && (
                <section className="progress panel" role="status">
                  <LoaderCircle className="spin" size={24} aria-hidden="true" />
                  <div><strong>Анализируем документы</strong><p>API вернёт результат по завершении. Анализ с LLM может занять несколько минут.</p><ol>{steps.map((step) => <li key={step}>{step}</li>)}</ol></div>
                </section>
              )}
              <Example mode={mode} files={exampleFiles} pending={pending} run={(resume) => analyze(() => api.example(mode, resume))} />
            </>
          ) : (
            <>
              {vacancy ? <a className="back" href={`#/${recordKey}`}><ArrowLeft size={16} /> К рейтингу вакансий</a> : <a className="back" href="#/"><ArrowLeft size={16} /> Новый анализ</a>}
              <Notices error={current?.error} />
              {!current && <div className="progress panel" role="status"><LoaderCircle className="spin" size={21} /> Загружаем результат…</div>}
              {result && (batch
                ? <Batch result={result} runUrl={(id) => path('runs', id)} />
                : <Match result={result} vacancy={vacancy} api={api} reportUrl={(id) => path('runs', result.run_id, id)} />)}
            </>
          )}
          <footer className="footer"><span>AIHR · Сопоставление резюме</span><span><ShieldCheck size={15} aria-hidden="true" /> Обезличивание документов перед вызовом модели</span></footer>
        </main>
      </div>
    </div>
  );
}

function Example({ mode, files, pending, run }) {
  const [resume, setResume] = useState('');
  return (
    <section className="example panel" aria-labelledby="example-title">
      <div className="example-info"><div className="icon-box lavender"><BookOpen size={21} aria-hidden="true" /></div>
        <div><h2 id="example-title">Пример из кейса</h2><p>{mode === 'batch' ? 'Сравните все резюме и вакансии из кейса МФТИ.' : 'Возьмите готовые документы из кейса МФТИ.'}</p></div>
      </div>
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
