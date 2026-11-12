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
      if (error.name === 'TimeoutError') throw new Error('API не ответил за 12 минут. Повторите запрос.');
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
    run: (id) => request(`/runs/${encodeURIComponent(id)}`),
    batch: (id) => request(`/batches/${encodeURIComponent(id)}`),
    outbound: (id) => request(`/runs/${encodeURIComponent(id)}/outbound`),
    reportUrl: (id, vacancy) => base + `/runs/${encodeURIComponent(id)}/report/${encodeURIComponent(vacancy)}.docx`,
  };
}
