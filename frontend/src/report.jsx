import React, { useEffect, useRef, useState } from 'react';
import { Clipboard, Download, FileText, LocateFixed, TriangleAlert, X } from 'lucide-react';
import { Tag } from './tag.jsx';

const evidenceLabels = { direct: 'Прямое', indirect: 'Косвенное', adjacent: 'Смежный навык' };
const modality = { must: 'Обязательное', nice: 'Желательное' };
const questionKinds = { factual: 'Уточнение фактов', behavioral: 'Вопрос об опыте' };
const thresholds = { years: 'Стаж, лет', education_level: 'Образование', language_level: 'Уровень языка' };

export function Report({ result, vacancy, api, score }) {
  const report = result.reports[vacancy.id];
  const [selection, setSelection] = useState(null);
  const [showResume, setShowResume] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const [log, setLog] = useState(null);
  const [logLoading, setLogLoading] = useState(false);
  const evidencePane = useRef(null);
  const fragments = [...(result.resume?.fragments || [])].sort((a, b) => a.order - b.order);
  const review = new Set(result.verdicts[vacancy.id]?.filter((item) => item.needs_review).map((item) => item.requirement_id));
  const activeIds = new Set(selection?.ids);

  useEffect(() => {
    if (!showResume || !selection?.ids.length) return;
    const fragment = evidencePane.current?.querySelector('[data-highlighted="true"]');
    fragment?.scrollIntoView({ block: 'nearest' });
  }, [selection, showResume]);

  if (!report) return <p className="empty">Отчёт недоступен для этой вакансии.</p>;

  function highlight(ids, rowId) {
    if (!ids.length) return;
    setSelection({ ids, rowId });
    setShowResume(true);
  }

  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(report.candidate_message);
      setCopyStatus('Письмо скопировано.');
    } catch {
      setCopyStatus('Копирование недоступно. Выделите текст письма вручную.');
    }
  }

  async function loadLog() {
    if (logLoading || log?.entries) return;
    setLogLoading(true);
    try {
      setLog(await api.outbound(result.run_id));
    } catch (failure) {
      setLog({ error: failure.message });
    } finally {
      setLogLoading(false);
    }
  }

  return (
    <>
      <section className="summary report-summary">
        {report.summary && <div><h2>Вывод по вакансии</h2><p>{report.summary}</p></div>}
        <div className="report-actions">{score}<a className="button secondary" href={api.reportUrl(result.run_id, vacancy.id)}><Download size={16} aria-hidden="true" /> Скачать DOCX</a></div>
      </section>

      <div className="section-heading">
        <h2>Требования и подтверждения</h2>
        {fragments.length > 0 && <button className="button secondary" type="button" aria-expanded={showResume}
          aria-controls="resume-viewer" onClick={() => setShowResume(!showResume)}>
          {showResume ? <X size={15} aria-hidden="true" /> : <FileText size={15} aria-hidden="true" />}
          {showResume ? 'Скрыть резюме' : 'Исходное резюме'}
        </button>}
      </div>
      <p className="table-hint">Прокрутите таблицу вправо, чтобы увидеть все колонки.</p>
      <div className={`report-grid${showResume ? ' with-resume' : ''}`}>
        <div className="table-scroll requirements-scroll" tabIndex={0} aria-label="Таблица требований">
          <table className="requirements">
            <caption className="sr-only">Сопоставление требований вакансии с резюме</caption>
            <thead><tr><th scope="col">Требование</th><th scope="col">Тип</th><th scope="col">Статус</th><th scope="col">Подтверждение из резюме</th><th scope="col">Комментарий</th></tr></thead>
            <tbody>{report.rows.map((row) => {
              const ids = row.resume_evidence.map(({ fragment_id }) => fragment_id);
              return (
                <tr key={row.requirement_id} className={showResume && selection?.rowId === row.requirement_id ? 'selected-row' : ''}
                  onClick={ids.length ? () => highlight(ids, row.requirement_id) : undefined}>
                  <th scope="row">{row.requirement}</th>
                  <td className="requirement-type">{modality[row.modality]}</td>
                  <td><Tag kind={row.status}>{row.status_ru}</Tag>{review.has(row.requirement_id) &&
                    <small className="manual"><TriangleAlert size={13} aria-hidden="true" /> Проверить вручную</small>}</td>
                  <td>
                    {!ids.length && <span className="muted">Нет цитаты из резюме</span>}
                    {row.resume_evidence.map((evidence, index) => (
                      <div className="quote" key={`${evidence.fragment_id}/${index}`}><small>{evidence.fragment_id}</small><blockquote>{evidence.quote}</blockquote></div>
                    ))}
                    {ids.length > 0 && <button className="text-button" type="button" aria-pressed={showResume && selection?.rowId === row.requirement_id}
                      aria-controls="resume-viewer"><LocateFixed size={15} aria-hidden="true" /> Показать в резюме</button>}
                  </td>
                  <td>
                    <span className="preserve">{row.comment}</span>
                    {row.evidence_type && <small>Доказательство · {evidenceLabels[row.evidence_type] || row.evidence_type}</small>}
                    {row.computed && <small>{row.computed}</small>}
                    {row.vacancy_quote && <details className="vacancy-quote" onClick={(event) => event.stopPropagation()}>
                      <summary>Цитата из вакансии</summary><blockquote>{row.vacancy_quote}</blockquote>
                    </details>}
                  </td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
        <aside className="resume-panel" id="resume-viewer" aria-labelledby="resume-pane-title" hidden={!showResume}>
          <div className="resume-head"><h3 id="resume-pane-title">Исходное резюме</h3>
            <p aria-live="polite">{activeIds.size ? `Подсвечено фрагментов: ${activeIds.size}` : 'Нажмите «Показать в резюме» у нужной цитаты.'}</p>
          </div>
          <div id="resume-fragments" className="fragment-scroll" ref={evidencePane} tabIndex={0} aria-label="Фрагменты резюме">
            {fragments.map((fragment) => (
              <div className="fragment" key={fragment.id} data-highlighted={activeIds.has(fragment.id)}>
                <small>{fragment.id}{fragment.section && ` · ${fragment.section}`}</small>
                <p className="preserve">{fragment.text}</p>
              </div>
            ))}
          </div>
        </aside>
      </div>

      <h2 className="section-title">Что учесть рекрутеру</h2>
      <div className="report-sections">
        {[
          ['Сильные стороны', report.strengths], ['Пробелы', report.gaps],
          ['Риски', report.risks], ['Сверх требований', report.beyond_requirements],
        ].map(([title, items]) => (
          <section className="report-section" key={title}><h3>{title}</h3>
            {items.length ? <ul>{items.map(({ text, fragment_ids }, index) => <li key={index}>{text}
              {fragment_ids.length > 0 && <button className="text-button references" onClick={() => highlight(fragment_ids)} aria-controls="resume-viewer"
                aria-label={`Показать фрагменты ${fragment_ids.join(', ')}`}>
                <LocateFixed size={14} aria-hidden="true" /> {fragment_ids.join(', ')}
              </button>}
            </li>)}</ul> : <p className="muted">Нет пунктов в отчёте.</p>}
          </section>
        ))}
        {report.questions.length > 0 && <section className="report-section"><h3>Вопросы кандидату</h3>
          <ol className="questions">{report.questions.map(({ text, kind, why }, index) => <li key={index}><strong>{text}</strong><small>{questionKinds[kind] || kind}</small><p>{why}</p></li>)}</ol>
        </section>}
      {report.recruiter_recommendation && <section className="report-section"><h3>Рекомендация рекрутеру</h3><p className="preserve">{report.recruiter_recommendation}</p></section>}
      {report.candidate_message && <section className="report-section"><h3>Письмо кандидату</h3><div><p className="preserve">{report.candidate_message}</p>
        <button className="button secondary" type="button" onClick={copyMessage}><Clipboard size={16} aria-hidden="true" /> Скопировать</button><p className="muted" role="status">{copyStatus}</p></div>
      </section>}
      </div>

      <div className="disclosures">
        {result.profile && <Profile profile={result.profile} />}
        <details><summary>Извлечённые требования вакансии</summary>
          <ul>{(result.requirements[vacancy.id] || []).map(({ id, text, modality: kind, threshold }) => (
            <li key={id}>{text}<small>{modality[kind]}{threshold && ` · ${thresholds[threshold.kind] || threshold.kind} · ${threshold.value}${threshold.subject ? ' · ' + threshold.subject : ''}`}</small></li>
          ))}</ul>
        </details>
        <details onToggle={(event) => { if (event.currentTarget.open) loadLog(); }}>
          <summary>Что ушло наружу</summary>
          {logLoading && <p role="status">Загружаем журнал…</p>}
          {log?.error && <div role="alert"><p>{log.error}</p><button className="button secondary" onClick={loadLog}>Повторить</button></div>}
          {log?.entries && (log.entries.length ? <pre>{JSON.stringify(log.entries, null, 2)}</pre> : <p>В журнале нет записей.</p>)}
        </details>
      </div>
    </>
  );
}

function Profile({ profile }) {
  const educationLabels = { secondary: 'Среднее', vocational: 'Среднее профессиональное', incomplete_higher: 'Незаконченное высшее', bachelor: 'Бакалавриат', specialist: 'Специалитет', master: 'Магистратура', phd: 'Кандидат наук', doctor: 'Доктор наук', course: 'Курсы' };
  return (
    <details><summary>Профиль кандидата</summary>
      {profile.total_experience_months != null && <p>Общий стаж · {profile.total_experience_months} мес.</p>}
      <div className="profile-grid">
        <div><h3>Опыт</h3><ul>{profile.positions.map((position, index) => (
          <li key={index}><strong>{position.title}</strong><small>{[position.organization, position.raw_dates, position.duration_months != null && `${position.duration_months} мес.`].filter(Boolean).join(' · ')}</small></li>
        ))}</ul></div>
        <div><h3>Образование</h3><ul>{profile.education.map((item, index) => (
          <li key={index}>{[item.institution, item.field, educationLabels[item.level], item.year_end].filter(Boolean).join(' · ')}</li>
        ))}</ul></div>
        <div><h3>Навыки</h3><p>{profile.skills.map(({ name }) => name).join(', ') || '—'}</p></div>
        <div><h3>Языки</h3><ul>{profile.languages.map((language, index) => (
          <li key={index}>{[language.name, language.level_raw, language.cefr !== language.level_raw && language.cefr].filter(Boolean).join(' · ')}</li>
        ))}</ul></div>
      </div>
    </details>
  );
}
