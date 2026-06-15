import { appendFile, readFile, rename, rm, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const DEFAULT_CORE_URL = 'https://os-sota.ru';
const DEFAULT_QUEUE_FILE = '.os-sota-sync-queue.jsonl';

function env(name, fallback = '') {
  return process.env[name] || fallback;
}

function boolEnv(name, fallback = true) {
  const value = env(name);
  if (!value) return fallback;
  return !['0', 'false', 'off', 'no'].includes(String(value).toLowerCase());
}

function nowIso() {
  return new Date().toISOString();
}

function queueFile() {
  return env('OS_SOTA_QUEUE_FILE', DEFAULT_QUEUE_FILE);
}

function connectorHeaders() {
  const headers = { 'content-type': 'application/json' };
  const connectorId = env('OS_SOTA_CONNECTOR_ID') || env('CORE_CONNECTOR_ID');
  const syncSecret = env('OS_SOTA_SYNC_SECRET') || env('CORE_PROJECT_SYNC_SECRET');
  const coreApiKey = env('OS_SOTA_CORE_API_KEY') || env('CORE_API_KEY');
  if (connectorId) headers['x-connector-id'] = connectorId;
  if (syncSecret) headers['x-project-sync-secret'] = syncSecret;
  if (coreApiKey) headers['x-core-api-key'] = coreApiKey;
  return headers;
}

function projectSlug() {
  return env('OS_SOTA_PROJECT_SLUG') || env('CORE_PROJECT_SLUG');
}

function sourceName() {
  return env('OS_SOTA_SOURCE') || projectSlug() || 'site';
}

function basePayload(extra = {}) {
  return {
    projectSlug: projectSlug(),
    source: sourceName(),
    environment: env('NODE_ENV', 'production'),
    sourceVersion: env('OS_SOTA_SOURCE_VERSION') || env('npm_package_version') || null,
    sentAt: nowIso(),
    ...extra
  };
}

function isConfigured() {
  return Boolean(projectSlug() && (env('OS_SOTA_SYNC_SECRET') || env('CORE_PROJECT_SYNC_SECRET') || env('OS_SOTA_CORE_API_KEY') || env('CORE_API_KEY')));
}

function eventId(path, payload) {
  return createHash('sha1').update(path + JSON.stringify(payload)).digest('hex');
}

async function enqueue(path, payload, reason = '') {
  if (!boolEnv('OS_SOTA_QUEUE_ENABLED', true)) return { queued: false, reason: 'queue disabled' };
  const item = {
    id: eventId(path, payload),
    path,
    payload,
    reason,
    attempts: 0,
    createdAt: nowIso()
  };
  await appendFile(queueFile(), JSON.stringify(item) + '\n', 'utf8');
  return { queued: true, id: item.id };
}

export async function osSotaPost(path, payload = {}, options = {}) {
  const safe = options.safe ?? false;
  const queueOnFail = options.queueOnFail ?? true;
  const timeoutMs = Number(env('OS_SOTA_TIMEOUT_MS', '15000'));
  const bodyPayload = basePayload(payload);

  if (!boolEnv('OS_SOTA_ENABLE_SYNC', true)) {
    return { ok: false, skipped: true, reason: 'OS_SOTA_ENABLE_SYNC is disabled' };
  }
  if (!isConfigured()) {
    const reason = 'OS SOTA env is not configured';
    if (safe) return { ok: false, skipped: true, reason };
    throw new Error(reason);
  }

  const baseUrl = env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL).replace(/\/+$/, '');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(baseUrl + path, {
      method: 'POST',
      headers: connectorHeaders(),
      body: JSON.stringify(bodyPayload),
      signal: controller.signal
    });
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
    if (!response.ok) throw new Error(data?.error || 'OS SOTA sync failed: HTTP ' + response.status);
    return data;
  } catch (error) {
    if (queueOnFail) await enqueue(path, bodyPayload, error.message);
    if (safe) return { ok: false, queued: queueOnFail, error: error.message };
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export const safeOsSotaPost = (path, payload = {}) => osSotaPost(path, payload, { safe: true, queueOnFail: true });

export async function osSotaGet(path, query = {}, options = {}) {
  const safe = options.safe ?? false;
  if (!boolEnv('OS_SOTA_ENABLE_SYNC', true)) {
    return { ok: false, skipped: true, reason: 'OS_SOTA_ENABLE_SYNC is disabled' };
  }
  if (!isConfigured()) {
    const reason = 'OS SOTA env is not configured';
    if (safe) return { ok: false, skipped: true, reason };
    throw new Error(reason);
  }
  const baseUrl = env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL).replace(/\/+$/, '');
  const params = new URLSearchParams({
    projectSlug: projectSlug() || '',
    source: sourceName(),
    ...query
  });
  try {
    const response = await fetch(baseUrl + path + '?' + params.toString(), {
      method: 'GET',
      headers: connectorHeaders()
    });
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
    if (!response.ok) throw new Error(data?.error || 'OS SOTA config pull failed: HTTP ' + response.status);
    return data;
  } catch (error) {
    if (safe) return { ok: false, error: error.message };
    throw error;
  }
}

export const pullOsSotaConfig = (options) => osSotaGet('/connectors/v1/config', {}, options);

export async function flushOsSotaQueue() {
  const file = queueFile();
  try {
    await stat(file);
  } catch {
    return { ok: true, flushed: 0, failed: 0, remaining: 0 };
  }
  const raw = await readFile(file, 'utf8');
  const items = raw.split(/\r?\n/).filter(Boolean).map((line) => {
    try { return JSON.parse(line); } catch { return null; }
  }).filter(Boolean);
  const failed = [];
  let flushed = 0;
  for (const item of items) {
    try {
      await osSotaPost(item.path, item.payload, { queueOnFail: false });
      flushed += 1;
    } catch (error) {
      failed.push({ ...item, attempts: (item.attempts || 0) + 1, reason: error.message, lastAttemptAt: nowIso() });
    }
  }
  if (failed.length) {
    const tmp = file + '.tmp';
    await appendFile(tmp, failed.map((item) => JSON.stringify(item)).join('\n') + '\n', 'utf8');
    await rename(tmp, file);
  } else {
    await rm(file, { force: true });
  }
  return { ok: failed.length === 0, flushed, failed: failed.length, remaining: failed.length };
}

export const sendOsSotaMetrics = (payload, options) => osSotaPost('/connectors/v1/metrics', payload, options);
export const sendOsSotaEvents = (events, options) => osSotaPost('/connectors/v1/events', { events }, options);
export const upsertOsSotaUsers = (users, options) => osSotaPost('/connectors/v1/users/upsert', { users }, options);
export const sendOsSotaSupportTicket = (payload, options) => osSotaPost('/connectors/v1/support/tickets', payload, options);
export const sendOsSotaErrors = (errors, options) => osSotaPost('/connectors/v1/errors', { errors }, options);
export const sendOsSotaBroadcastStats = (payload, options) => osSotaPost('/connectors/v1/broadcast/events', payload, options);
export const sendOsSotaPayments = (payments, options) => osSotaPost('/connectors/v1/commerce/payments', { payments }, options);
export const sendOsSotaSubscriptions = (subscriptions, options) => osSotaPost('/connectors/v1/commerce/subscriptions', { subscriptions }, options);
export const sendOsSotaPromoRedemptions = (redemptions, options) => osSotaPost('/connectors/v1/commerce/promo-redemptions', { redemptions }, options);
export const sendOsSotaAiUsage = (usage, options) => osSotaPost('/connectors/v1/ai/usage', { usage }, options);
export const sendOsSotaMarketingStats = (stats, options) => osSotaPost('/connectors/v1/marketing/stats', { stats }, options);
export const sendOsSotaFeatureUsage = (features, options) => osSotaPost('/connectors/v1/features/usage', { features }, options);
export const sendOsSotaDocuments = (documents, options) => osSotaPost('/connectors/v1/documents', { documents }, options);
export const sendOsSotaTasks = (tasks, options) => osSotaPost('/connectors/v1/tasks', { tasks }, options);

export const trackOsSotaEvent = (eventType, payload = {}, options) => sendOsSotaEvents([{ eventType, payload, createdAt: nowIso() }], options);
export const trackOsSotaPayment = (payment, options) => sendOsSotaPayments([payment], options);
export const trackOsSotaAiUsage = (usage, options) => sendOsSotaAiUsage([usage], options);
export const trackOsSotaFeature = (feature, action = 'used', payload = {}, options) => sendOsSotaFeatureUsage([{ feature, action, payload, createdAt: nowIso() }], options);
export const trackOsSotaTask = (task, options) => sendOsSotaTasks([task], options);
export const trackOsSotaDocument = (document, options) => sendOsSotaDocuments([document], options);
export const trackOsSotaError = (error, payload = {}, options) => {
  const title = error?.title || error?.name || 'Runtime error';
  const message = error?.message || String(error);
  return sendOsSotaErrors([{ level: payload.level || 'high', title, message, status: 'open', payload }], options);
};

export function installOsSotaProcessHandlers() {
  if (globalThis.__osSotaProcessHandlersInstalled) return;
  globalThis.__osSotaProcessHandlersInstalled = true;
  process.on('unhandledRejection', (reason) => {
    trackOsSotaError(reason instanceof Error ? reason : new Error(String(reason)), { source: 'unhandledRejection' }, { safe: true }).catch(() => {});
  });
  process.on('uncaughtException', (error) => {
    trackOsSotaError(error, { source: 'uncaughtException', level: 'critical' }, { safe: true }).catch(() => {});
  });
}

export function osSotaConfigStatus() {
  return {
    coreUrl: env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL),
    projectSlug: projectSlug() || null,
    source: sourceName(),
    connectorIdConfigured: Boolean(env('OS_SOTA_CONNECTOR_ID') || env('CORE_CONNECTOR_ID')),
    secretConfigured: Boolean(env('OS_SOTA_SYNC_SECRET') || env('CORE_PROJECT_SYNC_SECRET') || env('OS_SOTA_CORE_API_KEY') || env('CORE_API_KEY')),
    queueFile: queueFile(),
    queueEnabled: boolEnv('OS_SOTA_QUEUE_ENABLED', true),
    syncEnabled: boolEnv('OS_SOTA_ENABLE_SYNC', true)
  };
}

const isCliEntry = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isCliEntry && process.argv.includes('--check')) {
  console.log(JSON.stringify(osSotaConfigStatus(), null, 2));
}

if (isCliEntry && process.argv.includes('--flush')) {
  flushOsSotaQueue().then((result) => {
    console.log(JSON.stringify(result, null, 2));
    if (!result.ok) process.exitCode = 1;
  }).catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
