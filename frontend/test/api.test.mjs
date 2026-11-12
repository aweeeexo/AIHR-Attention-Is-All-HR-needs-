import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createApi } from '../src/api.js';

test('uploads original files and pasted UTF-8 text using the API multipart field names', async () => {
  const api = createApi('http://localhost:8000/', async (url, options) => {
    assert.equal(url, 'http://localhost:8000/match');
    assert.equal(options.method, 'POST');
    assert.equal(options.body.get('resume').name, 'резюме.txt');
    assert.equal(await options.body.get('resume').text(), 'Опыт работы');
    assert.deepEqual(options.body.getAll('vacancies').map((file) => file.name), ['v1.docx', 'вакансия.txt']);
    assert.equal(options.headers, undefined);
    return Response.json({ run_id: 'run' });
  });
  const vacancy = new File(['docx'], 'v1.docx');
  assert.deepEqual(await api.upload('single', [new File(['Опыт работы'], 'резюме.txt')], [
    vacancy, new File(['Описание'], 'вакансия.txt'),
  ]), { run_id: 'run' });
});

test('uses repeatable resumes in batch mode and encodes the live example selection', async () => {
  const names = ['a.txt', 'b.txt'];
  const api = createApi('http://localhost:8000', async (url, options) => {
    if (url.endsWith('/match/batch')) {
      assert.deepEqual(options.body.getAll('resumes').map((file) => file.name), names);
    } else {
      assert.equal(new URL(url).pathname, '/match/example');
      assert.equal(new URL(url).searchParams.get('resume'), 'Резюме + 1.docx');
    }
    return Response.json({});
  });
  await api.upload('batch', names.map((name) => new File(['text'], name)), [new File(['v'], 'v.txt')]);
  await api.example('single', 'Резюме + 1.docx');
});

test('reports HTTP errors and preserves partial file failures in successful responses', async () => {
  const api = createApi('http://localhost:8000', async () => Response.json({ detail: 'Прогон не найден' }, { status: 404 }));
  await assert.rejects(api.run('missing'), { message: 'Прогон не найден' });
  const partial = { errors: [{ code: 'E_CORRUPTED', filename: 'a.docx' }] };
  const success = createApi('http://localhost:8000', async () => Response.json(partial));
  assert.deepEqual(await success.example('batch'), partial);
});
