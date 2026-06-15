const DEFAULT_CORE_URL = 'https://os-sota.ru';

function env(name, fallback = '') {
  return process.env[name] || fallback;
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

function basePayload(extra = {}) {
  return {
    projectSlug: env('OS_SOTA_PROJECT_SLUG') || env('CORE_PROJECT_SLUG'),
    source: env('OS_SOTA_SOURCE') || env('CORE_PROJECT_SLUG') || 'site',
    ...extra
  };
}

export async function osSotaPost(path, payload = {}) {
  const baseUrl = env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL).replace(/\/+$/, '');
  const response = await fetch(baseUrl + path, {
    method: 'POST',
    headers: connectorHeaders(),
    body: JSON.stringify(basePayload(payload))
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!response.ok) throw new Error(data?.error || 'OS SOTA sync failed: HTTP ' + response.status);
  return data;
}

export const sendOsSotaMetrics = (payload) => osSotaPost('/connectors/v1/metrics', payload);
export const sendOsSotaEvents = (events) => osSotaPost('/connectors/v1/events', { events });
export const upsertOsSotaUsers = (users) => osSotaPost('/connectors/v1/users/upsert', { users });
export const sendOsSotaSupportTicket = (payload) => osSotaPost('/connectors/v1/support/tickets', payload);
export const sendOsSotaErrors = (errors) => osSotaPost('/connectors/v1/errors', { errors });
export const sendOsSotaBroadcastStats = (payload) => osSotaPost('/connectors/v1/broadcast/events', payload);
export const sendOsSotaPayments = (payments) => osSotaPost('/connectors/v1/commerce/payments', { payments });
export const sendOsSotaSubscriptions = (subscriptions) => osSotaPost('/connectors/v1/commerce/subscriptions', { subscriptions });
export const sendOsSotaPromoRedemptions = (redemptions) => osSotaPost('/connectors/v1/commerce/promo-redemptions', { redemptions });
export const sendOsSotaAiUsage = (usage) => osSotaPost('/connectors/v1/ai/usage', { usage });
export const sendOsSotaMarketingStats = (stats) => osSotaPost('/connectors/v1/marketing/stats', { stats });
export const sendOsSotaFeatureUsage = (features) => osSotaPost('/connectors/v1/features/usage', { features });
export const sendOsSotaDocuments = (documents) => osSotaPost('/connectors/v1/documents', { documents });
export const sendOsSotaTasks = (tasks) => osSotaPost('/connectors/v1/tasks', { tasks });

export function osSotaConfigStatus() {
  return {
    coreUrl: env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL),
    projectSlug: env('OS_SOTA_PROJECT_SLUG') || env('CORE_PROJECT_SLUG') || null,
    connectorIdConfigured: Boolean(env('OS_SOTA_CONNECTOR_ID') || env('CORE_CONNECTOR_ID')),
    secretConfigured: Boolean(env('OS_SOTA_SYNC_SECRET') || env('CORE_PROJECT_SYNC_SECRET') || env('OS_SOTA_CORE_API_KEY') || env('CORE_API_KEY'))
  };
}

if (process.argv.includes('--check')) {
  console.log(JSON.stringify(osSotaConfigStatus(), null, 2));
}
