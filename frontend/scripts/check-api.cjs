const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const ts = require('typescript');
const source = ts.transpileModule(readFileSync('src/lib/api.ts', 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
function client(fetch) {
  const events = [];
  const context = {exports: {}, process: {env: {}}, Headers, FormData, AbortSignal, Response, Event, CustomEvent, fetch, window: {dispatchEvent: event => events.push(event)}};
  vm.runInNewContext(source, context);
  return {...context.exports, events};
}
const response = (status, data) => new Response(JSON.stringify(data), {status, headers: {'Content-Type': 'application/json'}});
test('transport uses same-origin cookies, no-store, JSON, and cancellation', async () => {
  let captured;
  const api = client(async (url, init) => {captured = {url, init}; return response(200, {saved: true});});
  await api.post('/patients', {displayName: 'Synthetic patient'});
  assert.equal(captured.url, '/api/v1/patients');
  assert.equal(captured.init.credentials, 'same-origin');
  assert.equal(captured.init.cache, 'no-store');
  assert.equal(captured.init.headers.get('Content-Type'), 'application/json');
  assert.ok(captured.init.signal instanceof AbortSignal);
});
test('validation errors retain field details and request reference', async () => {
  const api = client(async () => response(422, {code: 'VALIDATION_ERROR', message: 'Check fields.', fieldErrors: {displayName: 'Required'}, requestId: 'synthetic-ref'}));
  await assert.rejects(api.api('/patients'), error => error.status === 422 && error.fieldErrors.displayName === 'Required' && error.requestId === 'synthetic-ref');
});
test('missing feature differs from missing clinical record', async () => {
  const missingFeature = client(async () => response(404, {code: 'NOT_FOUND', message: 'Not Found'}));
  await assert.rejects(missingFeature.api('/patients/opaque/summaries'), error => error.code === 'FEATURE_UNAVAILABLE');
  const missingRecord = client(async () => response(404, {code: 'NOT_FOUND', message: 'Patient unavailable.'}));
  await assert.rejects(missingRecord.api('/patients/opaque'), error => error.code === 'NOT_FOUND');
});
test('denied action emits its resource path for a separate patient-scope check', async () => {
  const api = client(async () => response(403, {message: 'Outside your permissions.'}));
  await assert.rejects(api.post('/patients/opaque/archive', {}));
  assert.equal(api.events[0].type, 'sanctum:denied');
  assert.equal(api.events[0].detail.path, '/patients/opaque/archive');
});
test('only protected 401 responses expire the current workspace', async () => {
  const api = client(async () => response(401, {message: 'Sign in.'}));
  await assert.rejects(api.post('/auth/login', {}));
  assert.equal(api.events.length, 0);
  await assert.rejects(api.api('/patients'));
  assert.equal(api.events[0].type, 'sanctum:expired');
});
test('network failure gives recovery guidance; an explicit abort is preserved', async () => {
  const failure = new TypeError('fetch failed');
  const api = client(async () => {throw failure;});
  await assert.rejects(api.api('/patients'), error => error.code === 'CONNECTION_FAILED' && error.message.includes('try again'));
  const controller = new AbortController(); controller.abort();
  await assert.rejects(api.api('/patients', {signal: controller.signal}), error => error === failure);
});
test('multipart requests preserve browser-generated content boundaries', async () => {
  let headers;
  const api = client(async (_url, init) => {headers = init.headers; return response(200, {});});
  await api.api('/documents', {method: 'POST', body: new FormData()});
  assert.equal(headers.has('Content-Type'), false);
});
