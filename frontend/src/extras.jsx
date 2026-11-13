import React, { useEffect, useState } from 'react';
import { Calculator, ClipboardCheck } from 'lucide-react';

const issueLabels = {
  discriminatory: 'Похоже на дискриминацию',
  unverifiable: 'Не проверить по резюме',
  vague: 'Расплывчато',
  too_many_must: 'Слишком много обязательных',
  duplicate: 'Дубль',
};
const fitLabels = { fits: 'подходит', fits_with_caveats: 'подходит с оговорками', not_fit: 'не подходит' };
const answers = [
  ['', 'Не отвечал'],
  ['match', 'Соответствует'],
  ['partial', 'Частично'],
  ['mismatch', 'Не соответствует'],
];

// Качество вакансии (D51): что не проверить по резюме, расплывчатое, «единорог», дискриминация, дубли
export function VacancyQuality({ api, runId, vacancyId }) {
  const [check, setCheck] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.vacancyCheck(runId)
      .then((checks) => { if (active) setCheck(checks.find((item) => item.vacancy_id === vacancyId) || null); })
      .catch((failure) => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [api, runId, vacancyId]);

  if (error || !check) return null;
  return (
    <section className="notice quality" aria-labelledby="quality-title">
      <ClipboardCheck size={20} aria-hidden="true" />
      <div>
        <strong id="quality-title">Качество вакансии</strong>
        <p>{check.summary}</p>
        {check.issues.length > 0 && <ul>{check.issues.map((issue, index) => (
          <li key={index}>
            <b>{issueLabels[issue.kind] || issue.kind}</b>{issue.requirement && ` · «${issue.requirement}»`}
            <small>{issue.text} → {issue.hint}</small>
          </li>
        ))}</ul>}
      </div>
    </section>
  );
}

export function whatIfText(change) {
  const [low, high] = change.interval_after;
  const place = change.place_before !== change.place_after
    ? `место ${change.place_before} → ${change.place_after}`
    : `место ${change.place_after} не изменилось`;
  return `Балл ${change.score_before} → ${change.score_after} (от ${low} до ${high}), `
    + `${fitLabels[change.label_before]} → ${fitLabels[change.label_after]}, ${place}.`;
}

// «Что если» (D50): ответ кандидата меняет статус — балл и рейтинг пересчитывает код, без LLM
export function WhatIf({ api, result, vacancy, report }) {
  const open = report.rows.filter(({ status }) => status === 'not_stated' || status === 'partial');
  const [choice, setChoice] = useState({});
  const [state, setState] = useState(null);
  const selected = Object.entries(choice).filter(([, status]) => status);

  if (!open.length) return null;

  async function recalc() {
    setState({ pending: true });
    try {
      const data = await api.whatIf(result.run_id, selected.map(([requirement_id, status]) => ({
        vacancy_id: vacancy.id, requirement_id, status,
      })));
      setState({ data, change: data.changes.find(({ vacancy_id }) => vacancy_id === vacancy.id) });
    } catch (failure) {
      setState({ error: failure.message });
    }
  }

  return (
    <section className="report-section whatif" aria-labelledby="whatif-title">
      <h3 id="whatif-title">Что если кандидат ответит</h3>
      <p className="muted">Отметьте ответы на уточняющие вопросы — балл и рейтинг пересчитаются той же формулой, без LLM. Результат анализа не меняется.</p>
      {open.map((row) => (
        <div className="whatif-row" key={row.requirement_id}>
          <div>{row.requirement}<small>Сейчас · {row.status_ru}</small></div>
          <select aria-label={`Ответ кандидата: ${row.requirement}`} value={choice[row.requirement_id] || ''}
            onChange={(event) => setChoice({ ...choice, [row.requirement_id]: event.target.value })}>
            {answers.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      ))}
      <button className="button primary" type="button" disabled={!selected.length || state?.pending} onClick={recalc}>
        <Calculator size={16} aria-hidden="true" /> Пересчитать
      </button>
      {state?.error && <p className="notice danger" role="alert">{state.error}</p>}
      {state?.change && (
        <div className="whatif-result" role="status">
          <p><strong>{whatIfText(state.change)}</strong></p>
          <p className="muted">Новый порядок вакансий: {state.data.ranking.items.map(({ vacancy_id }) => vacancy_id).join(' → ')}</p>
          {state.data.ranking.summary && <p>{state.data.ranking.summary}</p>}
        </div>
      )}
    </section>
  );
}
