import React from 'react';
import { ArrowUpRight, FileX as FileWarning, WarningCircle as CircleAlert } from '@phosphor-icons/react';
import { Report } from './report.jsx';
import { Tag } from './tag.jsx';

const statusLabels = {
  match: 'Соответствует',
  partial: 'Частично',
  mismatch: 'Не соответствует',
  not_stated: 'Не указано',
};
const fitLabels = { fits: 'Подходит', fits_with_caveats: 'Подходит с оговорками', not_fit: 'Не подходит' };
const timingLabels = { ingest: 'Загрузка', privacy: 'Обезличивание', extract: 'Извлечение', match: 'Сопоставление', score: 'Балл', report: 'Отчёт', total: 'Всего' };
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 20 });

export function Notices({ fallback, errors = [], warnings = [], error }) {
  if (!fallback && !errors.length && !warnings.length && !error) return null;
  return (
    <div className="notices">
      {error && <div className="notice danger" role="alert"><CircleAlert size={20} /><p>{error}</p></div>}
      {fallback && <div className="notice caution"><CircleAlert size={20} /><div><strong>Упрощённый анализ</strong><p>Часть этапов или весь анализ выполнены без LLM.</p></div></div>}
      {errors.map(({ code, filename, message, hint }, index) => (
        <div className="notice danger" key={index}><FileWarning size={20} /><div><strong>{filename}</strong><p>{message}</p>{hint && <p>{hint}</p>}<small>{code}</small></div></div>
      ))}
      {warnings.map((warning, index) => <div className="notice caution" key={index}><CircleAlert size={20} /><p>{warning}</p></div>)}
    </div>
  );
}

function Score({ item }) {
  return (
    <div className="score">
      <strong>{number.format(item.score)}</strong>
      <span>от {number.format(item.score_min)} до {number.format(item.score_max)}</span>
    </div>
  );
}

function Counts({ title, counts }) {
  return (
    <div className="count-group"><strong>{title} · {counts.total}</strong>
      <ul>{Object.entries(statusLabels).map(([status, label]) => <li key={status}><Tag kind={status}>{label} {counts[status]}</Tag></li>)}</ul>
    </div>
  );
}

export function Match({ result, vacancy, api, reportUrl }) {
  const { ranking } = result;
  const item = ranking?.items.find((entry) => entry.vacancy_id === vacancy?.id);
  return (
    <>
      <div className="result-heading">
        <h1>{vacancy ? item?.title || vacancy.title || vacancy.filename : 'Рейтинг вакансий'}</h1>
        {result.resume && <p>{result.resume.filename}</p>}
      </div>
      <Notices fallback={result.mode === 'fallback'} errors={result.errors} warnings={result.warnings} />
      {vacancy ? (
        <Report key={vacancy.id} result={result} vacancy={vacancy} api={api}
          score={item && <><Score item={item} /><Tag kind={item.label}>{fitLabels[item.label]}</Tag></>} />
      ) : ranking ? (
        <>
          {ranking.summary && <section className="summary"><h2>Итог для менеджера</h2><p>{ranking.summary}</p></section>}
          {ranking.items.length ? <div className="table-scroll" tabIndex={0} aria-label="Таблица рейтинга">
            <table className="ranking">
              <caption className="sr-only">Вакансии в порядке рейтинга</caption>
              <thead><tr><th scope="col" aria-label="Место">№</th><th scope="col">Вакансия</th><th scope="col">Балл и вердикт</th></tr></thead>
              <tbody>
                {ranking.items.map((entry, index) => {
                  const document = result.vacancies.find(({ id }) => id === entry.vacancy_id);
                  const title = entry.title || document?.filename || entry.vacancy_id;
                  return (
                    <tr key={entry.vacancy_id}>
                      <td className="rank">{index + 1}</td>
                      <th scope="row">
                        {result.reports[entry.vacancy_id] ? <a className="report-link" href={reportUrl(entry.vacancy_id)}
                          aria-label={`Открыть отчёт · ${title}`}><span>{title}</span><ArrowUpRight size={15} aria-hidden="true" /></a> : title}
                      <details className="rating-counts"><summary>Почему этот балл</summary>
                        <p className="ranking-explanation">{entry.explanation}</p>
                          <Counts title="Обязательные" counts={entry.must} /><Counts title="Желательные" counts={entry.nice} />
                        </details>
                      </th>
                    <td className="rank-score"><Score item={entry} /><Tag kind={entry.label}>{fitLabels[entry.label]}</Tag></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div> : <p className="empty">В рейтинге нет вакансий.</p>}
          <div className="disclosures">
            {ranking.comparison.length > 0 && <details><summary>Почему такой порядок</summary><ul>{ranking.comparison.map((line, index) => <li key={index}>{line}</li>)}</ul></details>}
            {ranking.formula && <details><summary>Как посчитано</summary><p className="preserve">{ranking.formula}</p></details>}
          </div>
        </>
      ) : <p className="empty">Рейтинг недоступен для этого прогона.</p>}
      {!!Object.keys(result.timings_ms).length && (
        <details className="section-disclosure"><summary>Время этапов</summary><dl className="timings">
          {Object.entries(result.timings_ms).map(([stage, ms]) => <div key={stage}><dt>{timingLabels[stage] || stage}</dt><dd>{number.format(ms)} мс</dd></div>)}
        </dl></details>
      )}
    </>
  );
}

export function Batch({ result, runUrl }) {
  const resumes = new Map(result.resumes.map((resume) => [resume.resume_id, resume]));
  const cells = new Map(result.cells.map((cell) => [`${cell.resume_id}/${cell.vacancy_id}`, cell]));
  return (
    <>
      <div className="result-heading"><h1>Матрица кандидатов</h1><p>Резюме: {result.resumes.length} · Вакансии: {result.vacancies.length}</p></div>
      <Notices fallback={result.resumes.some(({ mode }) => mode === 'fallback')} errors={[...result.errors, ...result.resumes.flatMap(({ error }) => error ? [error] : [])]} warnings={result.warnings} />
      {result.summary && <section className="summary"><h2>Итог по пакету</h2><p>{result.summary}</p></section>}
      {result.resumes.length > 0 && result.vacancies.length > 0 ? (
        <>
          <p className="table-hint">Прокрутите матрицу вправо, чтобы увидеть все вакансии.</p>
          <div className="table-scroll" tabIndex={0} aria-label="Матрица кандидатов и вакансий">
            <table className="matrix">
              <caption className="sr-only">Баллы кандидатов по вакансиям</caption>
              <thead><tr><th scope="col">Резюме</th>{result.vacancies.map((vacancy) => <th scope="col" key={vacancy.vacancy_id}>{vacancy.title || vacancy.filename}</th>)}</tr></thead>
              <tbody>{result.resumes.map((resume) => (
                <tr key={resume.resume_id}>
                  <th scope="row">{resume.run_id ? <a href={runUrl(resume.run_id)}>{resume.filename}</a> : resume.filename}</th>
                  {result.vacancies.map(({ vacancy_id }) => {
                    const cell = cells.get(`${resume.resume_id}/${vacancy_id}`);
                    return <td key={vacancy_id}>{cell ? <><Score item={cell} /><Tag kind={cell.label}>{fitLabels[cell.label]}</Tag></> : <span aria-label="Кандидат не обработан">—</span>}</td>;
                  })}
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      ) : <p className="empty">Матрица недоступна для этого пакета.</p>}
      {result.vacancies.length > 0 && <h2 className="section-title">Лучшие кандидаты по вакансиям</h2>}
      <div className="report-sections">{result.vacancies.map((vacancy) => (
        <section className="report-section" key={vacancy.vacancy_id}>
          <h3>{vacancy.title || vacancy.filename}</h3>
          <div>{vacancy.summary && <p className="preserve">{vacancy.summary}</p>}
          <ol>{vacancy.candidates.map((id) => {
            const resume = resumes.get(id);
            return <li key={id}>{resume?.run_id ? <a href={runUrl(resume.run_id)}>{resume.filename}</a> : resume?.filename || id}</li>;
          })}</ol></div>
        </section>
      ))}</div>
    </>
  );
}
