import React, { useRef, useState } from 'react';
import { ArrowRight, FileText, LoaderCircle, Paperclip, X } from 'lucide-react';

const formats = /\.(docx|pdf|rtf|txt)$/i;
const accepted = '.docx,.pdf,.rtf,.txt';

export function Upload({ mode, pending, submit }) {
  const [resumes, setResumes] = useState([]);
  const [vacancies, setVacancies] = useState([]);
  const [resumeText, setResumeText] = useState('');
  const [vacancyText, setVacancyText] = useState('');
  const [resumeSource, setResumeSource] = useState('file');
  const [vacancySource, setVacancySource] = useState('file');
  const batch = mode === 'batch';
  const activeResumeSource = batch ? 'file' : resumeSource;
  const resumeReady = activeResumeSource === 'text' ? resumeText.trim() : resumes.length;
  const vacancyReady = vacancySource === 'text' ? vacancyText.trim() : vacancies.length;
  const ready = resumeReady && vacancyReady && (!batch || resumes.length <= 50);

  function handleSubmit(event) {
    event.preventDefault();
    if (!ready || pending) return;
    const resumeDocs = activeResumeSource === 'text'
      ? [new File([resumeText], 'резюме.txt', { type: 'text/plain;charset=utf-8' })]
      : batch ? resumes : resumes.slice(0, 1);
    const vacancyDocs = vacancySource === 'text'
      ? [new File([vacancyText], 'вакансия.txt', { type: 'text/plain;charset=utf-8' })]
      : vacancies;
    submit(resumeDocs, vacancyDocs);
  }

  return (
    <form onSubmit={handleSubmit}>
      <fieldset disabled={pending} className="upload-fieldset">
        <UploadCard id="resume" title={batch ? 'Резюме кандидатов' : 'Резюме кандидата'}
          description={batch ? 'До 50 файлов, по одному на кандидата.' : undefined}
          files={batch ? resumes : resumes.slice(0, 1)} setFiles={setResumes} multiple={batch}
          limit={batch ? 50 : 1} canPaste={!batch} source={activeResumeSource} setSource={setResumeSource}
          value={resumeText} setValue={setResumeText} disabled={pending} />
        <UploadCard id="vacancy" title="Вакансии"
          files={vacancies} setFiles={setVacancies} multiple canPaste source={vacancySource} setSource={setVacancySource}
          value={vacancyText} setValue={setVacancyText} disabled={pending} />
        <div className="submit-row">
          {!ready && !pending && <span>Добавьте резюме и хотя бы одну вакансию.</span>}
          <button className="button primary" type="submit" disabled={!ready || pending}>
            {pending ? <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Обработка…</> : <>Начать анализ <ArrowRight size={16} aria-hidden="true" /></>}
          </button>
        </div>
      </fieldset>
    </form>
  );
}

function UploadCard({
  id, title, description, files, setFiles, multiple, limit,
  canPaste, source, setSource, value, setValue, disabled,
}) {
  const input = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [warning, setWarning] = useState('');

  function add(items) {
    if (disabled) return;
    const incoming = Array.from(items);
    if (!incoming.length) return;
    const valid = incoming.filter((file) => formats.test(file.name));
    const messages = [];
    if (valid.length < incoming.length) messages.push('Поддерживаются только DOCX, PDF, RTF и TXT.');
    if (valid.length) {
      const next = multiple ? [...files, ...valid] : valid.slice(0, 1);
      if (limit && (next.length > limit || (!multiple && valid.length > 1))) {
        messages.push(limit === 1 ? 'Добавлен первый файл. Для нескольких резюме выберите пакетный режим.' : `Можно добавить не больше ${limit} файлов.`);
      }
      setFiles(limit ? next.slice(0, limit) : next);
    }
    setWarning(messages.join(' '));
  }

  return (
    <section className="upload-card" aria-labelledby={`${id}-title`}>
      <div className="upload-head">
        <h2 id={`${id}-title`}>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {canPaste && <div className="source-control" role="group" aria-label={`Источник · ${title}`}>
        <button type="button" aria-pressed={source === 'file'} onClick={() => setSource('file')}>Файлы</button>
        <button type="button" aria-pressed={source === 'text'} onClick={() => setSource('text')}>Вставить текст</button>
      </div>}
      {source === 'text' ? (
        <textarea aria-label={`Текст · ${title}`} value={value} onChange={(event) => setValue(event.target.value)}
          placeholder={id === 'resume' ? 'Вставьте текст резюме' : 'Вставьте описание вакансии'} />
      ) : (
        <>
          <input hidden ref={input} type="file" accept={accepted} multiple={multiple} aria-label={`Файлы · ${title}`}
            onChange={(event) => { add(event.target.files); event.target.value = ''; }} />
          <button className={`dropzone ${dragging ? 'dragging' : ''}`} type="button"
            aria-label={`Выбрать файлы · ${title}`} onClick={() => input.current?.click()}
            onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); add(event.dataTransfer.files); }}>
            <Paperclip size={17} aria-hidden="true" />
            <span><strong>{files.length && !multiple ? 'Заменить файл' : multiple ? 'Выбрать файлы' : 'Выбрать файл'}</strong><span className="drop-instruction"> или перетащите сюда</span><small>DOCX, PDF, RTF, TXT</small></span>
          </button>
          {warning && <p className="input-warning" role="status">{warning}</p>}
          {!!files.length && (
            <ul className="file-list">
              {files.map((file, index) => (
                <li key={index}><FileText size={15} aria-hidden="true" /><span>{file.name}</span>
                  <button type="button" aria-label={`Удалить ${file.name}`} onClick={() => {
                    setFiles(files.filter((_, fileIndex) => fileIndex !== index));
                    setWarning('');
                  }}><X size={16} aria-hidden="true" /></button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
