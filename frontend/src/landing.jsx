import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowRight, CheckCircle, FileMagnifyingGlass, Calculator, LockKey, Quotes, Stack, UploadSimple,
} from '@phosphor-icons/react';

// Лендинг AIHR (скилл landing-page-design, макет A: первый экран и секции).
// Все цифры — из eval/report.md и реального прогона; ничего не придумано.

const CTA_HREF = '#/app';
const REPO = 'https://github.com/aweeeexo/AIHR-Attention-Is-All-HR-needs-';

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

function ProductShot() {
  const rows = [
    { place: 1, title: 'Frontend разработчик (Vue 3, Tailwind CSS)', score: '97,1', range: 'от 95,2 до 99,0', label: 'Подходит', kind: 'fits' },
    { place: 2, title: 'Куратор образовательного процесса', score: '50,0', range: 'от 5,8 до 94,2', label: 'Мало данных', kind: 'not_fit' },
    { place: 3, title: 'Специалист по учёту основных средств', score: '50,0', range: 'от 5,0 до 95,0', label: 'Мало данных', kind: 'not_fit' },
  ];
  return (
    <figure className="product-shot" aria-label="Пример результата: рейтинг вакансий и строка требования с цитатой">
      <div className="shot-head">
        <span className="caption-3">Рейтинг вакансий</span>
        <span className="caption-5">Резюме 3 из кейса · 3 вакансии</span>
      </div>
      <ol className="shot-list">
        {rows.map((row) => (
          <li key={row.place}>
            <span className="shot-place caption-3">{row.place}</span>
            <span className="shot-title body-5">{row.title}</span>
            <span className="shot-score">
              <span className="title-2">{row.score}</span>
              <span className="caption-5">{row.range}</span>
            </span>
            <span className={`tag ${row.kind}`}>{row.label}</span>
          </li>
        ))}
      </ol>
      <div className="shot-evidence">
        <div className="shot-requirement">
          <span className="body-5">Опыт работы от 1 года</span>
          <span className="tag match">Соответствует</span>
        </div>
        <blockquote className="caption-2">«Москва, март 2023 — настоящее время (2 года)»</blockquote>
        <span className="caption-5">Цитата из резюме, фрагмент подставлен кодом</span>
      </div>
      <figcaption className="sr-only">Пример настоящего результата AIHR на данных кейса.</figcaption>
    </figure>
  );
}

function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-copy">
        <h1 id="hero-title" className="hero-title gradient-text">
          Подбор вакансии<br />по доказательствам,<br />а не по проценту
        </h1>
        <p className="hero-sub title-2">
          AIHR сверяет резюме с каждым требованием вакансии и показывает цитату из документа.
          Рекрутер видит, на чём держится вывод и что уточнить у кандидата.
        </p>
        <div className="hero-actions">
          <a className="button primary button-md" href={CTA_HREF}>Проверить резюме <ArrowRight size={18} aria-hidden="true" /></a>
        </div>
        <p className="hero-proof caption-1">
          <CheckCircle size={18} weight="fill" aria-hidden="true" />
          86% статусов совпадают с ручной разметкой · ни одного ложного «не соответствует»
        </p>
      </div>
      <ProductShot />
    </section>
  );
}

function ProblemSolution() {
  return (
    <Reveal className="section split" aria-labelledby="problem-title">
      <h2 id="problem-title" className="heading-3 landing-title">Процент совпадения ничего не объясняет</h2>
      <div className="split-grid">
        <div className="panel">
          <h3 className="title-3 muted-title">Как сейчас</h3>
          <p className="body-3">
            Рекрутер вручную сверяет резюме с длинным списком требований. Сервисы подбора выдают число
            вроде «73% совпадения», но не говорят, откуда оно взялось и какие пункты не подтверждены.
          </p>
        </div>
        <div className="panel accent-panel">
          <h3 className="title-3">С AIHR</h3>
          <p className="body-3">
            Каждое требование получает один из четырёх статусов и цитату из резюме. Если сведений нет,
            система так и пишет и предлагает вопрос кандидату. Балл считает одна формула для всех вакансий.
          </p>
        </div>
      </div>
    </Reveal>
  );
}

const benefits = [
  { icon: Quotes, title: 'Цитата вместо догадки', text: 'Каждый вывод подкреплён фрагментом резюме. Текст цитаты подставляет код из документа, модель его не пишет.' },
  { icon: FileMagnifyingGlass, title: 'Нет сведений не значит нет навыка', text: 'Если в резюме об этом молчат, статус будет «не указано», а в отчёте появится вопрос кандидату.' },
  { icon: Calculator, title: 'Балл считает формула', text: 'Одна формула для всех вакансий, интервал неопределённости и объяснение, почему вакансия на этом месте.' },
  { icon: LockKey, title: 'Персональные данные остаются у вас', text: 'ФИО и контакты маскируются до любого запроса к модели. Журнал показывает, что именно ушло наружу.' },
  { icon: Stack, title: 'Пакет за один запуск', text: 'Несколько резюме против всех вакансий: матрица баллов и лучший кандидат на каждую позицию.' },
];

function Benefits() {
  return (
    <Reveal className="section" aria-labelledby="benefits-title">
      <h2 id="benefits-title" className="heading-3 landing-title">Что получает рекрутер</h2>
      <ul className="bento">
        {benefits.map(({ icon: Icon, title, text }) => (
          <li key={title} className="bento-item">
            <Icon size={24} aria-hidden="true" className="bento-icon" />
            <h3 className="title-2">{title}</h3>
            <p className="body-6 secondary">{text}</p>
          </li>
        ))}
      </ul>
    </Reveal>
  );
}

const TAGLINE = 'Каждый вывод опирается на цитату из резюме. Нет подтверждения, значит мы так и пишем.';

function TaglineReveal() {
  const words = TAGLINE.split(' ');
  const container = useRef(null);
  const [active, setActive] = useState(() => new Set());
  const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (reduced || !('IntersectionObserver' in window)) return undefined;
    const nodes = container.current?.querySelectorAll('[data-word]') || [];
    // Линия срабатывания — на 60% высоты окна: слова загораются по одному, в порядке чтения
    const observer = new IntersectionObserver((entries) => {
      setActive((prev) => {
        const next = new Set(prev);
        for (const entry of entries) {
          if (entry.isIntersecting) next.add(Number(entry.target.dataset.word));
        }
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

const steps = [
  { icon: UploadSimple, title: 'Загрузите документы', text: 'Резюме и вакансии в DOCX, PDF, RTF или TXT. Можно вставить текст или взять пример из кейса.' },
  { icon: LockKey, title: 'Система сверяет требования', text: 'Документы обезличиваются, требования разбираются по пунктам, каждый пункт сверяется с резюме.' },
  { icon: CheckCircle, title: 'Получите отчёт', text: 'Рейтинг вакансий, таблица с цитатами, вопросы кандидату и отчёт в DOCX для руководителя.' },
];

function HowItWorks() {
  return (
    <Reveal className="section" aria-labelledby="how-title">
      <h2 id="how-title" className="heading-3 landing-title">Как это работает</h2>
      <ol className="steps">
        {steps.map(({ icon: Icon, title, text }, index) => (
          <li key={title} className="step">
            <span className="step-number caption-3">Шаг {index + 1}</span>
            <Icon size={24} aria-hidden="true" className="bento-icon" />
            <h3 className="title-2">{title}</h3>
            <p className="body-6 secondary">{text}</p>
          </li>
        ))}
      </ol>
    </Reveal>
  );
}

const stats = [
  { value: '86%', label: 'статусов совпали с ручной разметкой на 200 пунктах' },
  { value: '0', label: 'ложных «не соответствует», когда в резюме просто нет сведений' },
  { value: '552 из 552', label: 'цитат найдены в резюме дословно' },
  { value: '4 из 4', label: 'лучших вакансий совпали с оценкой рекрутера' },
];

function Proof() {
  return (
    <Reveal className="section" aria-labelledby="proof-title">
      <h2 id="proof-title" className="heading-3 landing-title">Проверено на эталоне</h2>
      <p className="body-3 secondary section-lead">
        Четыре резюме и три вакансии кейса, 200 требований размечены вручную. Модель DeepSeek V4 Flash в Yandex AI Studio.
      </p>
      <ul className="stats">
        {stats.map(({ value, label }) => (
          <li key={label} className="stat">
            <span className="heading-4">{value}</span>
            <span className="body-6 secondary">{label}</span>
          </li>
        ))}
      </ul>
      <div className="table-card">
        <table className="compare">
          <caption className="title-3">Та же модель без нашей обвязки</caption>
          <thead>
            <tr><th scope="col" className="caption-3">Метрика</th><th scope="col" className="caption-3">Один запрос к модели</th><th scope="col" className="caption-3">AIHR</th></tr>
          </thead>
          <tbody className="body-6">
            <tr><th scope="row">Ложные «не соответствует»</th><td>5</td><td className="strong">0</td></tr>
            <tr><th scope="row">Цитаты дословно из резюме</th><td>70%</td><td className="strong">100%</td></tr>
            <tr><th scope="row">Точность статусов</th><td>70%</td><td className="strong">86%</td></tr>
          </tbody>
        </table>
      </div>
    </Reveal>
  );
}

const faq = [
  ['Чем это лучше, чем спросить ChatGPT?', 'Модель в AIHR не пишет цитаты и не считает балл. Она указывает номера фрагментов, а текст подставляет код; вывод без фрагмента автоматически становится «не указано». На той же модели простой запрос дал 5 ложных «не соответствует», у AIHR их ноль.'],
  ['Куда уходят персональные данные?', 'Перед любым запросом к модели ФИО, телефоны, почта, адреса и даты рождения заменяются метками. Отдельная проверка блокирует запрос, если в тексте остались контакты или имя. Журнал «Что ушло наружу» показывает точный текст каждого запроса.', 'faq-data'],
  ['Что если в резюме нет нужных сведений?', 'Требование получает статус «не указано», а не «не соответствует». Балл показывается с интервалом: от худшего до лучшего случая. В отчёте появляется вопрос кандидату, а вкладка «Что если» пересчитает балл после ответа.'],
  ['Можно ли доверять цитатам?', 'Да: каждая цитата взята из исходного документа по номеру фрагмента. На эталоне все 552 цитаты нашлись в резюме дословно. По клику цитата подсвечивается прямо в тексте резюме.'],
  ['Какие форматы файлов поддерживаются?', 'DOCX, PDF, RTF и TXT в любой кодировке, включая таблицы, колонтитулы и надписи. Битый файл даёт понятную ошибку и не останавливает анализ остальных. Скрытый белый текст вырезается и помечается.'],
  ['Работает ли система без ключа LLM и без интернета?', 'Да. Без ключа включается упрощённый режим на правилах и поиске по тексту: результат проще, но документы вообще не покидают ваш сервер.'],
  ['Сколько занимает анализ?', 'С внешней моделью одно резюме против трёх вакансий считается около полутора минут, интерфейс показывает этап и процент. Повторный анализ тех же документов берётся из кэша за секунды.'],
  ['Кто принимает решение о кандидате?', 'Только рекрутер. AIHR готовит доказательства, вопросы и черновик письма, но не отказывает и не приглашает сам.'],
];

function Faq() {
  return (
    <Reveal className="section" aria-labelledby="faq-title">
      <h2 id="faq-title" className="heading-3 landing-title">Вопросы и ответы</h2>
      <div className="faq">
        {faq.map(([question, answer, id]) => (
          <details key={question} id={id} className="faq-item">
            <summary className="title-3">{question}</summary>
            <p className="body-3 secondary">{answer}</p>
          </details>
        ))}
      </div>
    </Reveal>
  );
}

function FinalCta() {
  return (
    <Reveal className="section final-cta" aria-labelledby="final-title">
      <h2 id="final-title" className="heading-3">Проверьте одно резюме прямо сейчас</h2>
      <p className="body-3 secondary">
        Загрузите свои файлы или возьмите пример из кейса. Решение всегда за рекрутером.
      </p>
      <a className="button primary button-md" href={CTA_HREF}>Проверить резюме <ArrowRight size={18} aria-hidden="true" /></a>
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

export function Landing() {
  return (
    <>
      <Hero />
      <ProblemSolution />
      <Benefits />
      <TaglineReveal />
      <HowItWorks />
      <Proof />
      <Faq />
      <FinalCta />
    </>
  );
}
