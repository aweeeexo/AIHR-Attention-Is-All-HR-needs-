import React, { useEffect, useState } from 'react';
import { ArrowsClockwise, List, X } from '@phosphor-icons/react';
import { applyMode, storedMode } from './theme.js';

const links = [
  { href: '#/', label: 'О системе', match: (page) => page === 'landing' },
  { href: '#/app', label: 'Анализ', match: (page) => page === 'app' || page === 'result' },
];

function Status({ health, onRefresh }) {
  const state = health ? (health.status === 'ok' ? 'online' : 'offline') : health === null ? 'offline' : 'checking';
  const label = health
    ? (health.llm === 'configured' ? 'LLM подключена' : 'Без LLM')
    : health === null ? 'API недоступен' : 'Проверяем API';
  const retrieval = health && (health.retrieval === 'bm25+embeddings' ? 'BM25 и эмбеддинги' : 'BM25');
  return (
    <button className="nav-status" type="button" onClick={onRefresh}
      aria-label={['Обновить состояние API', label, retrieval].filter(Boolean).join('. ')}>
      <span className={`dot ${state}`} aria-hidden="true" />
      <span>{label}</span>
      <ArrowsClockwise size={14} aria-hidden="true" />
    </button>
  );
}

function ThemeSelect() {
  const [mode, setMode] = useState(storedMode);
  return (
    <label className="theme-select">
      <span className="sr-only">Тема оформления</span>
      <select className="caption-4" value={mode} onChange={(event) => { applyMode(event.target.value); setMode(event.target.value); }}>
        <option value="dark">Тёмная тема</option>
        <option value="light">Светлая тема</option>
      </select>
    </label>
  );
}

export function Nav({ page, health, onRefresh }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const close = () => setOpen(false);
    window.addEventListener('hashchange', close);
    return () => window.removeEventListener('hashchange', close);
  }, []);

  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  return (
    <header className="nav-wrap">
      <nav className="nav" aria-label="Основная навигация">
        <a className="brand" href="#/" aria-label="AIHR, на главную">AIHR</a>
        <ul className="nav-links">
          {links.map(({ href, label, match }) => (
            <li key={href}><a href={href} aria-current={match(page) ? 'page' : undefined}>{label}</a></li>
          ))}
        </ul>
        <div className="nav-tools">
          <Status health={health} onRefresh={onRefresh} />
          <ThemeSelect />
          <button className="icon-button menu-button" type="button" aria-expanded={open} aria-controls="mobile-menu"
            aria-label={open ? 'Закрыть меню' : 'Открыть меню'} onClick={() => setOpen(!open)}>
            <span className="icon-swap" data-state={open ? 'open' : 'closed'}>
              <List size={20} aria-hidden="true" className="icon-closed" />
              <X size={20} aria-hidden="true" className="icon-open" />
            </span>
          </button>
        </div>
      </nav>
      <div className="mobile-menu" id="mobile-menu" data-open={open} hidden={!open}>
        <ul>
          {links.map(({ href, label, match }, index) => (
            <li key={href} style={{ '--i': index }}>
              <a className="heading-4" href={href} aria-current={match(page) ? 'page' : undefined}>{label}</a>
            </li>
          ))}
        </ul>
      </div>
    </header>
  );
}
