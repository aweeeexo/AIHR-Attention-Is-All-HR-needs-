import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowRight, FileText, UploadSimple, X } from '@phosphor-icons/react';
import { setPendingResume } from './pending.js';

// Лендинг AIHR в стиле «документ с пометками»: действие — на первом экране,
// механизм (цитата к каждому выводу) — в иллюстрации. Данные иллюстраций — из реального
// прогона на резюме 1 кейса; цифры — из eval/report.md. Ничего не придумано.

const REPO = 'https://github.com/aweeeexo/AIHR-Attention-Is-All-HR-needs-';
const formats = /\.(docx|pdf|rtf|txt)$/i;

function useReveal() {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || visible) return undefined;
    if (!('IntersectionObserver' in window)) { setVisible(true); return undefined; }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: '0px 0px -10% 0px' });
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);
  return [ref, visible];
}

function Reveal({ as: Tag = 'section', className = '', children, ...props }) {
  const [ref, visible] = useReveal();
  return <Tag ref={ref} className={`reveal ${visible ? 'is-visible' : ''} ${className}`} {...props}>{children}</Tag>;
}

function SectionHead({ number, id, title, lead }) {
  return (
    <header className="section-head">
      <span className="section-number caption-3" aria-hidden="true">{number}</span>
      <h2 id={id} className="heading-3">{title}</h2>
      {lead && <p className="body-3 secondary">{lead}</p>}
    </header>
  );
}

// ---------- Первый экран: действие ----------

function HeroAction({ api, onDone }) {
  const input = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');

  function pick(files) {
    const chosen = Array.from(files || [])[0];
    if (!chosen) return;
    if (!formats.test(chosen.name)) {
      setError(`Файл «${chosen.name}» не подходит. Нужен DOCX, PDF, RTF или TXT.`);
      return;
    }
    setError('');
    setFile(chosen);
  }

  async function start(request) {
    setError('');
    setJob({ stage: 'Отправляем документы', progress: 0 });
    try {
      const started = await request();
      const result = await api.waitJob(started, setJob);
      onDone(result);
    } catch (failure) {
      setError(failure.message);
      setJob(null);
    }
  }

  if (job) {
    const share = Math.round((job.progress || 0) * 100);
    return (
      <div className="hero-action" role="status" aria-live="polite">
        <div className="progress-head">
          <span className="title-3">{job.stage}</span>
          <span className="caption-1 tabular">{share}%</span>
        </div>
        <div className="progress-bar" role="progressbar" aria-label="Готовность анализа" aria-valuemin={0} aria-valuemax={100} aria-valuenow={share}>
          <span style={{ transform: `scaleX(${share / 100})` }} />
        </div>
        <p className="caption-2 secondary">С внешней моделью одно резюме считается около полутора минут. Пример из кейса после прогрева открывается за секунды.</p>
      </div>
    );
  }

  return (
    <div className="hero-action">
      <input hidden ref={input} type="file" accept=".docx,.pdf,.rtf,.txt" aria-label="Файл резюме"
        onChange={(event) => { pick(event.target.files); event.target.value = ''; }} />
      {!file ? (
        <button type="button" id="hero-drop" className={`drop-sheet ${dragging ? 'dragging' : ''}`} onClick={() => input.current?.click()}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => { event.preventDefault(); setDragging(false); pick(event.dataTransfer.files); }}>
          <UploadSimple size={28} aria-hidden="true" />
          <span className="title-2">Перетащите резюме сюда</span>
          <span className="body-6 secondary">или нажмите, чтобы выбрать файл · DOCX, PDF, RTF, TXT</span>
        </button>
      ) : (
        <div className="picked">
          <div className="picked-file">
            <FileText size={22} aria-hidden="true" />
            <span className="body-5">{file.name}</span>
            <button type="button" className="icon-button" aria-label="Убрать файл" onClick={() => setFile(null)}><X size={16} /></button>
          </div>
          <button type="button" className="button primary button-md" onClick={() => start(() => api.startCase(file))}>
            Сравнить с вакансиями кейса <ArrowRight size={18} aria-hidden="true" />
          </button>
          <a className="text-link button-sm" href="#/app" onClick={() => setPendingResume(file)}>Добавить свои вакансии</a>
        </div>
      )}
      {error && <p className="caption-2 error-text" role="alert">{error}</p>}
      {!file && (
        <button type="button" className="text-link button-sm" onClick={() => start(() => api.startExample('single'))}>
          Нет резюме под рукой? Посмотрите пример из кейса
        </button>
      )}
    </div>
  );
}

// ---------- Иллюстрация: лист резюме, выделения и линии к требованиям ----------

const marks = [
  { id: 'R15', before: '', mark: 'Опыт работы: 2 года 10 месяцев', after: '', kind: 'match' },
  { id: 'R7', before: 'Трекер привычек — Telegram Mini App: ', mark: 'вёрстка на HTML и CSS', after: ', календарь, напоминания…', kind: 'partial' },
  { id: 'R9', before: '…интерфейсы я собирал на чистом JS, ', mark: 'с Tailwind тоже пока не работал', after: '.', kind: 'mismatch' },
];
const requirements = [
  { text: 'Опыт работы от 1 года', status: 'Соответствует', kind: 'match', link: 'R15' },
  { text: 'Вёрстка макетов на HTML, CSS, JS с нуля', status: 'Частично', kind: 'partial', link: 'R7' },
  { text: 'Практический опыт с Tailwind CSS', status: 'Не соответствует', kind: 'mismatch', link: 'R9' },
  { text: 'Опыт работы с Pinia', status: 'Не указано', kind: 'not_stated', link: null },
];

function DocFigure() {
  const box = useRef(null);
  const [paths, setPaths] = useState([]);

  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return undefined;
    const draw = () => {
      if (window.matchMedia('(max-width: 900px)').matches) { setPaths([]); return; }
      const base = node.getBoundingClientRect();
      const next = [];
      for (const req of requirements) {
        if (!req.link) continue;
        const from = node.querySelector(`[data-mark="${req.link}"]`)?.getBoundingClientRect();
        const to = node.querySelector(`[data-req="${req.link}"]`)?.getBoundingClientRect();
        if (!from || !to) continue;
        const x1 = from.right - base.left + 4;
        const y1 = from.top + from.height / 2 - base.top;
        const x2 = to.left - base.left - 6;
        const y2 = to.top + to.height / 2 - base.top;
        const mid = (x1 + x2) / 2;
        next.push({ id: req.link, kind: req.kind, d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`, x2, y2 });
      }
      setPaths(next);
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <figure className="doc-figure" ref={box} aria-label="Как AIHR связывает требования вакансии с цитатами из резюме">
      <div className="sheet-stack">
        <div className="sheet sheet-back" aria-hidden="true" />
        <div className="sheet sheet-front">
          <p className="sheet-label caption-3">Резюме 1 из кейса</p>
          {marks.map((line) => (
            <div className="sheet-line" key={line.id}>
              <span className="frag-id caption-3">{line.id}</span>
              <p className="body-6"><span className="secondary">{line.before}</span><mark className={`hl ${line.kind}`} data-mark={line.id}>{line.mark}</mark><span className="secondary">{line.after}</span></p>
            </div>
          ))}
          <div className="sheet-line ghost" aria-hidden="true"><span className="frag-id caption-3">R21</span><span className="ghost-bar w-70" /></div>
          <div className="sheet-line ghost" aria-hidden="true"><span className="frag-id caption-3">R23</span><span className="ghost-bar w-40" /></div>
        </div>
      </div>
      <ol className="req-list">
        <li className="req-head caption-3">Требования вакансии «Frontend разработчик»</li>
        {requirements.map((req) => (
          <li key={req.text} className="req" data-req={req.link || undefined}>
            <span className="body-5">{req.text}</span>
            <span className={`tag ${req.kind}`}>{req.status}</span>
            <span className="caption-5 muted">{req.link ? `Фрагмент ${req.link}` : 'В резюме нет сведений'}</span>
          </li>
        ))}
      </ol>
      <svg className="connectors" aria-hidden="true">
        {paths.map((p) => (
          <g key={p.id} className={`conn ${p.kind}`}>
            <path d={p.d} />
            <circle cx={p.x2} cy={p.y2} r="3" />
          </g>
        ))}
      </svg>
      <figcaption className="caption-5 muted">Реальный прогон: резюме 1 и вакансия 1 кейса. Цитаты подставлены из документа кодом.</figcaption>
    </figure>
  );
}

function Hero({ api, onDone }) {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-copy">
        <h1 id="hero-title" className="hero-title gradient-text">Подбор вакансии<br />по доказательствам</h1>
        <p className="hero-sub title-2">
          AIHR сверяет резюме с каждым требованием вакансии и показывает цитату из документа.
          Видно, на чём держится вывод и что уточнить у кандидата.
        </p>
        <HeroAction api={api} onDone={onDone} />
        <p className="hero-proof caption-1">84% статусов совпадают с ручной разметкой · 0 ложных «не соответствует»</p>
      </div>
      <DocFigure />
    </section>
  );
}

// ---------- 01. Как читать результат ----------

const notes = [
  ['Требование', 'Вакансия разбита на отдельные пункты: обязательные и желательные, с порогами стажа, образования и языка.'],
  ['Статус', 'Один из четырёх. Цвет всегда идёт вместе с подписью, поэтому таблицу можно читать и при печати без цвета.'],
  ['Цитата', 'Дословный фрагмент резюме. Модель указывает только номер фрагмента, текст подставляет код.'],
  ['Номер фрагмента', 'По клику фрагмент подсвечивается прямо в тексте резюме: вывод легко проверить глазами.'],
  ['Комментарий и расчёт', 'Чего не хватает и как посчитан стаж: «2 года 10 месяцев не меньше 1 года».'],
];

function Anatomy() {
  return (
    <Reveal className="section" aria-labelledby="anatomy-title">
      <SectionHead number="01" id="anatomy-title" title="Как читать результат"
        lead="Каждая строка таблицы отвечает на один вопрос: подтверждает ли резюме это требование и чем именно." />
      <div className="anatomy">
        <div className="sheet anatomy-row">
          <span className="callout" data-n="1"><span className="body-4">Опыт работы от 1 года</span></span>
          <span className="callout" data-n="2"><span className="tag match">Соответствует</span></span>
          <span className="callout" data-n="3"><mark className="hl match body-6">Опыт работы: 2 года 10 месяцев</mark></span>
          <span className="callout" data-n="4"><span className="frag-id caption-3">R15</span></span>
          <span className="callout" data-n="5"><span className="body-6 secondary">Стаж посчитан кодом: 2 г. 10 мес. ≥ 1 года</span></span>
        </div>
        <ol className="notes">
          {notes.map(([title, text]) => (
            <li key={title}><span className="title-3">{title}</span><span className="body-6 secondary">{text}</span></li>
          ))}
        </ol>
      </div>
    </Reveal>
  );
}

// ---------- 02. Четыре статуса ----------

const statuses = [
  ['match', 'Соответствует', 'В резюме есть прямое подтверждение.', 'Опыт работы: 2 года 10 месяцев'],
  ['partial', 'Частично', 'Подтверждена часть: меньше срок, ниже уровень или смежный навык.', 'вёрстка на HTML и CSS'],
  ['mismatch', 'Не соответствует', 'Только если в резюме есть факт, который противоречит требованию.', 'с Tailwind тоже пока не работал'],
  ['not_stated', 'Не указано', 'В резюме об этом молчат. Это не минус, а вопрос кандидату.', 'фрагмента нет'],
];

function Statuses() {
  return (
    <Reveal className="section" aria-labelledby="statuses-title">
      <SectionHead number="02" id="statuses-title" title="Четыре статуса вместо процента"
        lead="«Не указано» и «не соответствует» означают разное. Если подтверждения нет, система так и пишет и не ставит минус за молчание." />
      <dl className="legend">
        {statuses.map(([kind, label, text, example]) => (
          <div className="legend-row" key={kind}>
            <dt><span className={`tag ${kind}`}>{label}</span></dt>
            <dd className="body-3">{text}</dd>
            <dd className="legend-example">
              {kind === 'not_stated'
                ? <span className="hl not_stated body-6">{example}</span>
                : <mark className={`hl ${kind} body-6`}>{example}</mark>}
            </dd>
          </div>
        ))}
      </dl>
    </Reveal>
  );
}

// ---------- Большая фраза: слова проявляются по одному ----------

const TAGLINE = 'Каждый вывод опирается на цитату из резюме. Нет подтверждения, значит мы так и пишем.';

function TaglineReveal() {
  const words = TAGLINE.split(' ');
  const container = useRef(null);
  const [active, setActive] = useState(() => new Set());
  const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (reduced || !('IntersectionObserver' in window)) return undefined;
    const nodes = container.current?.querySelectorAll('[data-word]') || [];
    const observer = new IntersectionObserver((entries) => {
      setActive((prev) => {
        const next = new Set(prev);
        for (const entry of entries) if (entry.isIntersecting) next.add(Number(entry.target.dataset.word));
        return next;
      });
    }, { rootMargin: '0px 0px -40% 0px' });
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [reduced]);

  return (
    <section className="section tagline" aria-label="Главный принцип">
      <p ref={container} className="tagline-text heading-2">
        {words.map((word, index) => (
          <span key={index} data-word={index} className={reduced || active.has(index) ? 'on' : ''}>{word} </span>
        ))}
      </p>
    </section>
  );
}

// ---------- 03. Как это работает ----------

const steps = [
  ['Загрузите документы', 'Резюме и вакансии в DOCX, PDF, RTF или TXT. Можно вставить текст или взять пример из кейса.'],
  ['Система сверяет требования', 'Документы обезличиваются, вакансия делится на пункты, каждый пункт сверяется с резюме.'],
  ['Получите отчёт', 'Рейтинг вакансий, таблица с цитатами, вопросы кандидату и отчёт в DOCX для руководителя.'],
];

function HowItWorks() {
  return (
    <Reveal className="section" aria-labelledby="how-title">
      <SectionHead number="03" id="how-title" title="Как это работает" />
      <ol className="timeline">
        {steps.map(([title, text], index) => (
          <li key={title}>
            <span className="timeline-n heading-5" aria-hidden="true">{index + 1}</span>
            <span className="title-2">{title}</span>
            <span className="body-6 secondary">{text}</span>
          </li>
        ))}
      </ol>
    </Reveal>
  );
}

// ---------- 04. Проверено на эталоне ----------

function Proof() {
  return (
    <Reveal className="section" aria-labelledby="proof-title">
      <SectionHead number="04" id="proof-title" title="Проверено на эталоне"
        lead="Четыре резюме и три вакансии кейса, 200 требований размечены вручную. Модель DeepSeek V4 Flash в Yandex AI Studio." />
      <div className="figures">
        <div className="figure-main">
          <span className="figure-big tabular">84%</span>
          <span className="body-3 secondary">статусов совпали с ручной разметкой</span>
        </div>
        <ul className="figure-side">
          <li><span className="heading-4 tabular">0</span><span className="body-6 secondary">ложных «не соответствует», когда в резюме просто нет сведений</span></li>
          <li><span className="heading-4 tabular">525 из 525</span><span className="body-6 secondary">цитат найдены в резюме дословно</span></li>
          <li><span className="heading-4 tabular">4 из 4</span><span className="body-6 secondary">лучших вакансий совпали с оценкой рекрутера</span></li>
        </ul>
      </div>
      <div className="sheet compare-sheet">
        <table className="compare">
          <caption className="title-3">Та же модель, если просто спросить её одним запросом</caption>
          <thead><tr><th scope="col" className="caption-3">Метрика</th><th scope="col" className="caption-3">Один запрос</th><th scope="col" className="caption-3">AIHR</th></tr></thead>
          <tbody className="body-6">
            <tr><th scope="row">Ложные «не соответствует»</th><td><mark className="hl mismatch">5</mark></td><td className="strong">0</td></tr>
            <tr><th scope="row">Цитаты дословно из резюме</th><td><mark className="hl partial">70%</mark></td><td className="strong">100%</td></tr>
            <tr><th scope="row">Точность статусов</th><td>70%</td><td className="strong">84%</td></tr>
          </tbody>
        </table>
      </div>
    </Reveal>
  );
}

// ---------- 05. Персональные данные ----------

function Privacy() {
  return (
    <Reveal className="section" aria-labelledby="privacy-title">
      <SectionHead number="05" id="privacy-title" title="Персональные данные не уходят наружу"
        lead="Перед любым запросом к модели ФИО, контакты и адреса заменяются метками. Отдельная проверка блокирует запрос, если в тексте остались имя или контакты." />
      <div className="redaction">
        <div className="sheet">
          <p className="sheet-label caption-3">Резюме у вас</p>
          <p className="body-6">Иванова Мария Сергеевна</p>
          <p className="body-6">Телефон: +7 912 345 67 80, maria.ivanova@mail.ru</p>
          <p className="body-6">г. Казань, ул. Баумана, д. 12</p>
          <p className="body-6 secondary">2019 — 2024, ООО «Сфера», бухгалтер. Вела учёт в 1С.</p>
        </div>
        <ArrowRight size={28} aria-hidden="true" className="redaction-arrow" />
        <div className="sheet">
          <p className="sheet-label caption-3">Что получает модель</p>
          <p className="body-6"><span className="redact">[CANDIDATE] [CANDIDATE] [CANDIDATE]</span></p>
          <p className="body-6">Телефон: <span className="redact">[PHONE_1]</span>, <span className="redact">[EMAIL_1]</span></p>
          <p className="body-6"><span className="redact">[ADDRESS]</span></p>
          <p className="body-6 secondary">2019 — 2024, ООО «Сфера», бухгалтер. Вела учёт в 1С.</p>
        </div>
      </div>
      <p className="caption-2 muted">Данные в примере вымышлены, метки справа — настоящий результат модуля обезличивания. Журнал «Что ушло наружу» в отчёте показывает каждый запрос.</p>
    </Reveal>
  );
}

// ---------- 06. Вопросы и ответы: список слева, ответ справа ----------

const faq = [
  ['Чем это лучше, чем спросить ChatGPT?', 'Модель в AIHR не пишет цитаты и не считает балл. Она указывает номера фрагментов, а текст подставляет код; вывод без фрагмента автоматически становится «не указано». На той же модели простой запрос дал 5 ложных «не соответствует», у AIHR их ноль.'],
  ['Куда уходят персональные данные?', 'Перед запросом к модели ФИО, телефоны, почта, адреса и даты рождения заменяются метками. Отдельная проверка блокирует запрос, если в тексте остались контакты или имя. Журнал «Что ушло наружу» показывает точный текст каждого запроса.'],
  ['Что если в резюме нет нужных сведений?', 'Требование получает статус «не указано», а не «не соответствует». Балл показывается с интервалом от худшего до лучшего случая. В отчёте появляется вопрос кандидату, а вкладка «Что если» пересчитает балл после ответа.'],
  ['Можно ли доверять цитатам?', 'Каждая цитата взята из исходного документа по номеру фрагмента. На эталоне все 525 цитат нашлись в резюме дословно. По клику цитата подсвечивается прямо в тексте резюме.'],
  ['Какие форматы файлов поддерживаются?', 'DOCX, PDF, RTF и TXT в любой кодировке, включая таблицы, колонтитулы и надписи. Битый файл даёт понятную ошибку и не останавливает анализ остальных. Скрытый белый текст вырезается и помечается.'],
  ['Работает ли система без ключа LLM и без интернета?', 'Да. Без ключа включается упрощённый режим на правилах и поиске по тексту: результат проще, но документы вообще не покидают ваш сервер.'],
  ['Сколько занимает анализ?', 'С внешней моделью одно резюме против трёх вакансий считается около полутора минут, интерфейс показывает этап и процент. Повторный анализ тех же документов берётся из кэша за секунды.'],
  ['Кто принимает решение о кандидате?', 'Только рекрутер. AIHR готовит доказательства, вопросы и черновик письма, но не отказывает и не приглашает сам.'],
];

function Faq() {
  const [current, setCurrent] = useState(0);
  return (
    <Reveal className="section" aria-labelledby="faq-title">
      <SectionHead number="06" id="faq-title" title="Вопросы и ответы" />
      <div className="faq">
        <ul className="faq-list" role="tablist" aria-label="Вопросы">
          {faq.map(([question], index) => (
            <li key={question}>
              <button type="button" role="tab" id={index === 1 ? 'faq-data' : undefined} aria-selected={current === index}
                aria-controls="faq-answer" className="body-5" onClick={() => setCurrent(index)}>{question}</button>
            </li>
          ))}
        </ul>
        <div className="sheet faq-answer" id="faq-answer" role="tabpanel" aria-live="polite">
          <h3 className="title-1">{faq[current][0]}</h3>
          <p className="body-3 secondary">{faq[current][1]}</p>
        </div>
        <div className="faq-mobile">
          {faq.map(([question, answer]) => (
            <div key={question}><h3 className="title-3">{question}</h3><p className="body-6 secondary">{answer}</p></div>
          ))}
        </div>
      </div>
    </Reveal>
  );
}

function FinalCta() {
  return (
    <Reveal className="section final-cta" aria-labelledby="final-title">
      <h2 id="final-title" className="heading-3">Проверьте одно резюме прямо сейчас</h2>
      <p className="body-3 secondary">Документы обрабатываются на вашем сервере, во внешнюю модель уходит только обезличенный текст. Решение всегда за рекрутером.</p>
      <button type="button" className="button primary button-md" onClick={() => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
        setTimeout(() => document.getElementById('hero-drop')?.focus(), 400);
      }}>Перетащить резюме <ArrowRight size={18} aria-hidden="true" /></button>
    </Reveal>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <p className="caption-5">AIHR · Attention Is All HR Needs · хакатон «ИИ в системе управления МФТИ»</p>
      <ul className="footer-links caption-4">
        <li><a href="#/faq/data">Обработка данных</a></li>
        <li><a href={REPO} target="_blank" rel="noreferrer">Исходный код и документация</a></li>
      </ul>
    </footer>
  );
}

export function Landing({ api, onDone }) {
  return (
    <>
      <Hero api={api} onDone={onDone} />
      <Anatomy />
      <Statuses />
      <TaglineReveal />
      <HowItWorks />
      <Proof />
      <Privacy />
      <Faq />
      <FinalCta />
    </>
  );
}
