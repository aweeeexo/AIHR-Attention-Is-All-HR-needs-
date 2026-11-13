import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, ArrowRight } from '@phosphor-icons/react';
import { IconContext } from '@phosphor-icons/react';
import '@fontsource-variable/manrope';
import './tokens.css';
import './style.css';
import { createApi } from './api.js';
import { Upload } from './upload.jsx';
import { Batch, Match, Notices } from './results.jsx';
import { Nav } from './nav.jsx';
import { Footer, Landing } from './landing.jsx';
import { PageSkeleton, RankingSkeleton } from './skeleton.jsx';

const api = createApi(import.meta.env.VITE_API_URL || 'http://localhost:8000');

// Маршруты в hash: #/ — лендинг, #/app — анализ, #/runs/<id>[/<вакансия>], #/batches/<id>
function readRoute() {
  const hash = window.location.hash.replace(/^#/, '') || '/';
  const parts = hash.split('/').filter(Boolean);
  if (!parts.length) return { page: 'landing' };
  if (parts[0] === 'faq' && parts[1] === 'data') return { page: 'landing', anchor: 'faq-data' };
  if (parts[0] === 'app' && parts.length === 1) return { page: 'app' };
  if (['runs', 'batches'].includes(parts[0]) && parts[1]) {
    return { page: 'result', kind: parts[0], id: parts[1], vacancy: parts[2] };
  }
  return { page: 'missing' };
}

function path(kind, id, vacancy) {
  return `#/${kind}/${encodeURIComponent(id)}${vacancy ? '/' + encodeURIComponent(vacancy) : ''}`;
}

function App() {
  const [route, setRoute] = useState(readRoute);
  const [health, setHealth] = useState(undefined);
  const [exampleFiles, setExampleFiles] = useState(null);

  async function checkConnection() {
    setHealth(undefined);
    const [status, files] = await Promise.allSettled([api.health(), api.files()]);
    setHealth(status.status === 'fulfilled' ? status.value : null);
    setExampleFiles(files.status === 'fulfilled' ? files.value : null);
  }

  useEffect(() => {
    checkConnection();
    const navigate = () => {
      setRoute(readRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);

  useEffect(() => {
    if (!route.anchor) return;
    const target = document.getElementById(route.anchor);
    if (target) {
      if (target.tagName === 'DETAILS') target.open = true;
      target.scrollIntoView({ block: 'center' });
    }
  }, [route]);

  return (
    <IconContext.Provider value={{ weight: 'regular' }}>
      <a className="skip-link button-sm" href="#main" onClick={(event) => {
        event.preventDefault();
        document.getElementById('main')?.focus();
      }}>Перейти к содержимому</a>
      <Nav page={route.page} health={health} onRefresh={checkConnection} />
      <main id="main" tabIndex={-1} className={`main ${route.page}`}>
        {route.page === 'landing' && <Landing />}
        {route.page === 'app' && <Analysis files={exampleFiles} />}
        {route.page === 'result' && <Result route={route} />}
        {route.page === 'missing' && <NotFound />}
      </main>
      <Footer />
    </IconContext.Provider>
  );
}

function Progress({ job }) {
  const share = Math.round((job?.progress || 0) * 100);
  return (
    <section className="progress-card" role="status" aria-live="polite">
      <div className="progress-head">
        <span className="title-3">{job?.stage || 'Отправляем документы'}</span>
        <span className="caption-1 tabular">{share}%</span>
      </div>
      <div className="progress-bar" role="progressbar" aria-label="Готовность анализа" aria-valuemin={0} aria-valuemax={100} aria-valuenow={share}>
        <span style={{ transform: `scaleX(${share / 100})` }} />
      </div>
      <p className="caption-2 secondary">С внешней моделью одно резюме считается около полутора минут. Пример из кейса после прогрева открывается за секунды.</p>
      <RankingSkeleton />
    </section>
  );
}

function Analysis({ files }) {
  const [mode, setMode] = useState('single');
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState('');
  const busy = useRef(false);

  async function analyze(request) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setProgress(null);
    setError('');
    try {
      const job = await request();
      const value = await api.waitJob(job, setProgress);
      window.location.hash = value.batch_id ? path('batches', value.batch_id) : path('runs', value.run_id);
    } catch (failure) {
      setError(failure.message);
    } finally {
      busy.current = false;
      setPending(false);
      setProgress(null);
    }
  }

  return (
    <div className="container page">
      <header className="page-head">
        <h1 className="heading-4">Новый анализ</h1>
        <p className="body-3 secondary">Загрузите резюме и вакансии или запустите пример из кейса.</p>
      </header>
      <div className="segmented" role="group" aria-label="Режим анализа">
        <button type="button" className="button-sm" aria-pressed={mode === 'single'} disabled={pending} onClick={() => setMode('single')}>Одно резюме</button>
        <button type="button" className="button-sm" aria-pressed={mode === 'batch'} disabled={pending} onClick={() => setMode('batch')}>Пакет резюме</button>
      </div>
      <div className="analysis-layout">
        <div className="analysis-main">
          <Upload mode={mode} pending={pending} submit={(resumes, vacancies) => analyze(() => api.startUpload(mode, resumes, vacancies))} />
          <Notices error={error} />
          {pending && <Progress job={progress} />}
        </div>
        <Example mode={mode} files={files} pending={pending} run={(resume) => analyze(() => api.startExample(mode, resume))} />
      </div>
    </div>
  );
}

function Example({ mode, files, pending, run }) {
  const [resume, setResume] = useState('');
  return (
    <aside className="card example" aria-labelledby="example-title">
      <h2 id="example-title" className="title-2">Пример из кейса</h2>
      <p className="body-6 secondary">{mode === 'batch' ? 'Все четыре резюме против трёх вакансий кейса.' : 'Одно резюме из кейса против трёх вакансий.'}</p>
      {mode === 'single' && Boolean(files?.resumes.length) && (
        <label className="field">
          <span className="caption-1">Резюме</span>
          <select className="body-6" value={files.resumes.includes(resume) ? resume : ''} onChange={(event) => setResume(event.target.value)} disabled={pending}>
            <option value="">Первое резюме</option>
            {files.resumes.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
      )}
      <button className="button secondary button-md" type="button" disabled={pending || files === null}
        onClick={() => run(files?.resumes.includes(resume) ? resume : '')}>
        Запустить пример <ArrowRight size={18} aria-hidden="true" />
      </button>
      {files === null && <p className="caption-2 error-text">API недоступен: пример запустить нельзя. Проверьте, что сервер запущен.</p>}
    </aside>
  );
}

function Result({ route }) {
  const [record, setRecord] = useState(null);
  const cache = useRef(new Map());
  const key = `${route.kind}/${route.id}`;

  useEffect(() => {
    let active = true;
    const stored = cache.current.get(key);
    if (stored) { setRecord({ key, value: stored }); return undefined; }
    setRecord(null);
    const load = route.kind === 'runs' ? api.run : api.batch;
    load(decodeURIComponent(route.id)).then((value) => {
      if (!active) return;
      cache.current.set(key, value);
      setRecord({ key, value });
    }).catch((failure) => { if (active) setRecord({ key, error: failure.message }); });
    return () => { active = false; };
  }, [key, route.kind, route.id]);

  const current = record?.key === key ? record : null;
  const result = current?.value;
  const batch = route.kind === 'batches';
  const vacancy = result && !batch && result.vacancies.find(({ id }) => encodeURIComponent(id) === route.vacancy);

  return (
    <div className="container page">
      <div className="crumbs">
        {vacancy
          ? <a className="back button-sm" href={path('runs', route.id)}><ArrowLeft size={16} aria-hidden="true" /> К рейтингу вакансий</a>
          : <a className="back button-sm" href="#/app"><ArrowLeft size={16} aria-hidden="true" /> Новый анализ</a>}
      </div>
      <Notices error={current?.error} />
      {!current && <PageSkeleton />}
      {result && (batch
        ? <Batch result={result} runUrl={(id) => path('runs', id)} />
        : <Match result={result} vacancy={vacancy} api={api} reportUrl={(id) => path('runs', result.run_id, id)} />)}
    </div>
  );
}

function NotFound() {
  return (
    <div className="container page empty-state">
      <p className="caption-3 secondary">Ошибка 404</p>
      <h1 className="heading-3">Такой страницы нет</h1>
      <p className="body-3 secondary">Ссылка устарела или в ней опечатка. Начните новый анализ или вернитесь на главную.</p>
      <div className="empty-actions">
        <a className="button primary button-md" href="#/app">Новый анализ</a>
        <a className="button secondary button-md" href="#/">На главную</a>
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
