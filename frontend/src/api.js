export function createApi(baseUrl, fetcher = fetch) {
  const base = baseUrl.trim().replace(/\/+$/, '');

  async function request(path, options) {
    try {
      const response = await fetcher(base + path, {
        signal: AbortSignal.timeout(12 * 60 * 1000),
        ...options,
      });
      if (!response.ok) {
        const { detail } = await response.json().catch(() => ({}));
        const message = Array.isArray(detail) ? detail.map(({ msg }) => msg).join(' · ') : detail;
        throw new Error(message || `Ошибка API (${response.status})`);
      }
      return await response.json();
    } catch (error) {
      if (error.name === 'TimeoutError') throw new Error(path === '/vacancies/url' ? 'Сайт вакансии отвечает слишком долго. Загрузите вакансию файлом.' : 'API не ответил за 12 минут. Повторите запрос.');
      if (error instanceof TypeError) throw new Error('Не удалось подключиться к API. Проверьте, запущен ли сервер.');
      throw error;
    }
  }

  return {
    health: () => request('/health', { signal: AbortSignal.timeout(5000) }),
    files: () => request('/example/files', { signal: AbortSignal.timeout(8000) }),
    example(mode, resume) {
      if (mode === 'batch') return request('/match/batch/example', { method: 'POST' });
      const query = resume ? `?${new URLSearchParams({ resume })}` : '';
      return request('/match/example' + query, { method: 'POST' });
    },
    upload(mode, resumes, vacancies) {
      const batch = mode === 'batch';
      const body = new FormData();
      for (const resume of resumes) body.append(batch ? 'resumes' : 'resume', resume);
      for (const vacancy of vacancies) body.append('vacancies', vacancy);
      return request(batch ? '/match/batch' : '/match', { method: 'POST', body });
    },
    // Асинхронные задачи (D48): API сразу отвечает job_id, этап и процент берём из GET /jobs/{id}
    startExample(mode, resume) {
      if (mode === 'batch') return request('/jobs/batch/example', { method: 'POST' });
      const query = resume ? `?${new URLSearchParams({ resume })}` : '';
      return request('/jobs/match/example' + query, { method: 'POST' });
    },
    startUpload(mode, resumes, vacancies) {
      const batch = mode === 'batch';
      const body = new FormData();
      for (const resume of resumes) body.append(batch ? 'resumes' : 'resume', resume);
      for (const vacancy of vacancies) body.append('vacancies', vacancy);
      return request(batch ? '/jobs/batch' : '/jobs/match', { method: 'POST', body });
    },
    startCase(resume) {
      const body = new FormData();
      body.append('resume', resume);
      return request('/jobs/match/case', { method: 'POST', body });
    },
    // Реестр открытых вакансий (D58): вакансии хранятся на сервере, на анализ уходит только резюме
    startRegistry(mode, resumes) {
      const batch = mode === 'batch';
      const body = new FormData();
      for (const resume of resumes) body.append(batch ? 'resumes' : 'resume', resume);
      return request(batch ? '/jobs/batch/registry' : '/jobs/match/registry', { method: 'POST', body });
    },
    vacancies: () => request('/vacancies', { signal: AbortSignal.timeout(8000) }),
    addVacancies(files) {
      const body = new FormData();
      for (const file of files) body.append('files', file);
      return request('/vacancies', { method: 'POST', body });
    },
    addVacancyUrl: (url) => request('/vacancies/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
      signal: AbortSignal.timeout(40000),
    }),
    async deleteVacancy(id) {
      try {
        const response = await fetcher(`${base}/vacancies/${encodeURIComponent(id)}`, { method: 'DELETE', signal: AbortSignal.timeout(8000) });
        if (!response.ok && response.status !== 404) throw new Error(`Ошибка API (${response.status})`);
      } catch (error) {
        if (error instanceof TypeError) throw new Error('Не удалось подключиться к API. Проверьте, запущен ли сервер.');
        throw error;
      }
    },
    job: (id) => request(`/jobs/${encodeURIComponent(id)}`, { signal: AbortSignal.timeout(15000) }),
    async waitJob(job, onProgress = () => {}, { interval = 800, sleep } = {}) {
      const pause = sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
      let current = job;
      onProgress(current);
      while (current.status === 'queued' || current.status === 'running') {
        await pause(interval);
        current = await this.job(current.job_id);
        onProgress(current);
      }
      if (current.status === 'failed') throw new Error(`Расчёт не удался: ${current.error || 'неизвестная ошибка'}`);
      return current.batch_id ? this.batch(current.batch_id) : this.run(current.run_id);
    },
    whatIf: (id, answers) => request(`/runs/${encodeURIComponent(id)}/whatif`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    }),
    vacancyCheck: (id) => request(`/runs/${encodeURIComponent(id)}/vacancy-check`),
    run: (id) => request(`/runs/${encodeURIComponent(id)}`),
    batch: (id) => request(`/batches/${encodeURIComponent(id)}`),
    outbound: (id) => request(`/runs/${encodeURIComponent(id)}/outbound`),
    reportUrl: (id, vacancy) => base + `/runs/${encodeURIComponent(id)}/report/${encodeURIComponent(vacancy)}.docx`,
  };
}
