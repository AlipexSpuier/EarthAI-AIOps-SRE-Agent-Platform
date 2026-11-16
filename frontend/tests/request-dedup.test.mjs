import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build } from 'esbuild';

const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
// Expose the private request only in the in-memory test module, not the production API.
const compiled = await build({ stdin: { contents: `${source}\nexport { request as testRequest };`, loader: 'ts', sourcefile: 'src/lib/api.ts' }, write: false, platform: 'node', target: 'node22', format: 'esm' });
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`;
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
let moduleId = 0;
let api;
let ApiError;
let testRequest;
let requests;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function response(data, status = 200) { return { ok: status >= 200 && status < 300, status, json: async () => data }; }

beforeEach(async () => {
  ({ api, ApiError, testRequest } = await import(`${moduleUrl}#${moduleId++}`));
  requests = [];
  globalThis.window = new EventTarget();
  globalThis.fetch = (url, options) => {
    const gate = deferred();
    requests.push({ url, options, ...gate });
    return gate.promise;
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

test('identical concurrent default GETs share one fetch through JSON parsing and effect replay', async () => {
  const first = api.get('/servers');
  const second = api.get('/servers');
  assert.strictEqual(first, second);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/servers');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.deepEqual(requests[0].options.headers, {});

  const json = deferred();
  requests[0].resolve({ ok: true, status: 200, json: () => json.promise });
  await Promise.resolve();
  const replay = api.get('/servers');
  assert.strictEqual(replay, first);
  assert.equal(requests.length, 1);
  const data = [{ id: 'server-one' }];
  json.resolve(data);
  const results = await Promise.all([first, second, replay]);
  for (const result of results) assert.strictEqual(result, data);
});

test('only exactly matching paths, including query strings, are shared', async () => {
  const paths = ['/servers?tag=one', '/servers?tag=two', '/skills'];
  const pending = paths.map(path => api.get(path));
  assert.equal(requests.length, 3);
  requests.forEach((request, index) => request.resolve(response({ path: paths[index] })));
  assert.deepEqual(await Promise.all(pending), paths.map(path => ({ path })));
});

test('a completed GET is not a cache and the next refresh receives new data', async () => {
  const first = api.get('/servers');
  requests[0].resolve(response({ revision: 1 }));
  assert.deepEqual(await first, { revision: 1 });
  const refresh = api.get('/servers');
  assert.notStrictEqual(refresh, first);
  assert.equal(requests.length, 2);
  requests[1].resolve(response({ revision: 2 }));
  assert.deepEqual(await refresh, { revision: 2 });
});

test('a failed shared fetch is removed and can be retried', async () => {
  const first = api.get('/servers');
  const second = api.get('/servers');
  const failure = new TypeError('offline');
  const rejected = assert.rejects(Promise.all([first, second]), error => error === failure);
  requests[0].reject(failure);
  await rejected;
  const retry = api.get('/servers');
  assert.equal(requests.length, 2);
  requests[1].resolve(response({ revision: 2 }));
  assert.deepEqual(await retry, { revision: 2 });
});

test('a JSON parsing failure is removed and can be retried', async () => {
  const first = api.get('/servers');
  const rejected = assert.rejects(first, SyntaxError);
  requests[0].resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError('invalid JSON'); } });
  await rejected;
  const retry = api.get('/servers');
  assert.equal(requests.length, 2);
  requests[1].resolve(response([]));
  assert.deepEqual(await retry, []);
});

test('401 is not cached and retains unauthorized dispatch rules and error text', async () => {
  let unauthorized = 0;
  window.addEventListener('earthai:unauthorized', () => { unauthorized += 1; });
  for (const path of ['/servers', '/auth/me', '/auth/login', '/auth/register']) {
    const index = requests.length;
    const first = api.get(path);
    const duplicate = api.get(path);
    assert.strictEqual(first, duplicate);
    const rejected = assert.rejects(Promise.all([first, duplicate]), error => error instanceof ApiError && error.status === 401 && error.message === '请先登录');
    requests[index].resolve(response({ detail: '请先登录' }, 401));
    await rejected;
    assert.equal(unauthorized, 1);
    const retry = api.get(path);
    assert.equal(requests.length, index + 2);
    requests[index + 1].resolve(response({ id: 'account-b' }));
    assert.deepEqual(await retry, { id: 'account-b' });
  }
});

const writes = [
  ['login POST', () => api.post('/auth/login', { account: 'account-b' })],
  ['logout POST', () => api.post('/auth/logout')],
  ['PATCH', () => api.patch('/auth/me', { name: 'account-b' })],
  ['DELETE', () => api.delete('/files/file-one')],
  ['upload', () => api.upload('/files', new File(['test'], 'test.txt', { type: 'text/plain' }))],
];
for (const [name, write] of writes) {
  test(`${name} invalidates GETs both before and after the write`, async () => {
    const previous = api.get('/auth/me');
    const mutation = write();
    const during = api.get('/auth/me');
    assert.notStrictEqual(during, previous);
    assert.strictEqual(api.get('/auth/me'), during);
    assert.equal(requests.length, 3);
    assert.equal(requests[1].options.credentials, 'same-origin');
    if (name === 'upload') {
      assert.ok(requests[1].options.body instanceof FormData);
      assert.equal(requests[1].options.body.get('file').name, 'test.txt');
      assert.equal(requests[1].options.headers['Content-Type'], undefined);
    }
    requests[1].resolve(response(undefined, 204));
    assert.equal(await mutation, undefined);
    const current = api.get('/auth/me');
    assert.notStrictEqual(current, during);
    assert.equal(requests.length, 4);
    requests[0].resolve(response({ id: 'account-a' }));
    requests[2].resolve(response({ id: 'account-a' }));
    requests[3].resolve(response({ id: 'account-b' }));
    assert.deepEqual(await Promise.all([previous, during, current]), [{ id: 'account-a' }, { id: 'account-a' }, { id: 'account-b' }]);
  });
}

test('a failed write also invalidates GETs at completion', async () => {
  const previous = api.get('/auth/me');
  const mutation = api.post('/auth/logout');
  const rejected = assert.rejects(mutation, /offline/);
  const during = api.get('/auth/me');
  requests[1].reject(new TypeError('offline'));
  await rejected;
  const current = api.get('/auth/me');
  assert.notStrictEqual(current, during);
  assert.equal(requests.length, 4);
  for (const index of [0, 2, 3]) requests[index].resolve(response({ id: 'account-a' }));
  await Promise.all([previous, during, current]);
});

test('an old GET finally cannot remove a newer same-path GET after an account write', async () => {
  const previous = api.get('/auth/me');
  const login = api.post('/auth/login', { account: 'account-b' });
  requests[1].resolve(response({ id: 'account-b' }));
  await login;
  const current = api.get('/auth/me');
  requests[0].resolve(response({ id: 'account-a' }));
  assert.deepEqual(await previous, { id: 'account-a' });
  assert.strictEqual(api.get('/auth/me'), current);
  assert.equal(requests.length, 3);
  requests[2].resolve(response({ id: 'account-b' }));
  assert.deepEqual(await current, { id: 'account-b' });
});

test('GETs with headers bypass sharing and their finally cannot remove the default GET', async () => {
  const normal = api.get('/files');
  const compact = testRequest('/files', { headers: { 'X-View': 'compact' } });
  const expanded = testRequest('/files', { headers: { 'X-View': 'expanded' } });
  const repeated = testRequest('/files', { headers: { 'X-View': 'compact' } });
  assert.equal(requests.length, 4);
  assert.equal(requests[1].options.headers['X-View'], 'compact');
  assert.equal(requests[2].options.headers['X-View'], 'expanded');
  for (const index of [1, 2, 3]) requests[index].resolve(response({ view: index }));
  await Promise.all([compact, expanded, repeated]);
  assert.strictEqual(api.get('/files'), normal);
  assert.equal(requests.length, 4);
  requests[0].resolve(response([]));
  await normal;
});

test('GETs with AbortSignal are independent and an aborted caller cannot evict or abort the default GET', async () => {
  const normal = api.get('/files');
  const firstController = new AbortController();
  const secondController = new AbortController();
  const first = testRequest('/files', { signal: firstController.signal });
  const second = testRequest('/files', { signal: secondController.signal });
  assert.equal(requests.length, 3);
  assert.strictEqual(requests[1].options.signal, firstController.signal);
  assert.strictEqual(requests[2].options.signal, secondController.signal);
  const rejected = assert.rejects(first, { name: 'AbortError' });
  firstController.abort();
  requests[1].reject(firstController.signal.reason);
  await rejected;
  assert.equal(secondController.signal.aborted, false);
  assert.strictEqual(api.get('/files'), normal);
  assert.equal(requests.length, 3);
  requests[0].resolve(response([]));
  requests[2].resolve(response({ independent: true }));
  assert.deepEqual(await Promise.all([normal, second]), [[], { independent: true }]);
});

test('identical concurrent POSTs are never deduplicated', async () => {
  const first = api.post('/projects', { name: 'one' });
  const second = api.post('/projects', { name: 'one' });
  assert.notStrictEqual(first, second);
  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.options.method, 'POST');
    assert.equal(request.options.body, JSON.stringify({ name: 'one' }));
    assert.equal(request.options.headers['Content-Type'], 'application/json');
  }
  requests[0].resolve(response({ id: 'project-one' }));
  requests[1].resolve(response({ id: 'project-two' }));
  assert.deepEqual(await Promise.all([first, second]), [{ id: 'project-one' }, { id: 'project-two' }]);
});
