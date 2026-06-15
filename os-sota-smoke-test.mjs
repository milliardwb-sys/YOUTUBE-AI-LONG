import {
  osSotaConfigStatus,
  sendOsSotaMetrics,
  sendOsSotaEvents,
  upsertOsSotaUsers,
  sendOsSotaPayments,
  sendOsSotaSubscriptions,
  sendOsSotaPromoRedemptions,
  sendOsSotaBroadcastStats,
  sendOsSotaAiUsage,
  sendOsSotaMarketingStats,
  sendOsSotaFeatureUsage,
  sendOsSotaSupportTicket,
  sendOsSotaErrors,
  sendOsSotaDocuments,
  sendOsSotaTasks
} from './os-sota-core-client.mjs';

const shouldSend = process.argv.includes('--send');
const now = new Date().toISOString();
const runId = 'smoke-' + Date.now();

const samples = {
  metrics: {
    users: 12,
    newUsers: 2,
    activeUsers: 7,
    revenue: 1000,
    expenses: 250,
    ticketsOpen: 1,
    ticketsClosed: 0,
    apiCost: 0.12,
    currency: 'RUB',
    apiCurrency: 'USD'
  },
  users: [{
    externalId: runId + '-user',
    email: runId + '@example.com',
    name: 'OS SOTA Smoke User',
    status: 'active',
    registered: true,
    onboardingDone: true,
    firstActionDone: true,
    paymentDone: true,
    secondVisitDone: false
  }],
  events: [{
    eventType: 'smoke.product_event',
    userExternalId: runId + '-user',
    sessionId: runId,
    page: '/smoke',
    payload: { runId },
    createdAt: now
  }],
  payments: [{
    externalPaymentId: runId + '-payment',
    userExternalId: runId + '-user',
    userEmail: runId + '@example.com',
    amount: 1000,
    currency: 'RUB',
    status: 'paid',
    provider: 'os-sota-smoke',
    tariffCode: 'SMOKE',
    promoCode: 'SMOKE10',
    paidAt: now,
    payload: { runId }
  }],
  subscriptions: [{
    externalId: runId + '-subscription',
    userExternalId: runId + '-user',
    userEmail: runId + '@example.com',
    tariffCode: 'SMOKE',
    status: 'active',
    startsAt: now,
    limits: { generations: 10 },
    usage: { generations: 1 },
    payload: { runId }
  }],
  redemptions: [{
    code: 'SMOKE10',
    userExternalId: runId + '-user',
    userEmail: runId + '@example.com',
    orderId: runId + '-order',
    discountAmount: 100,
    currency: 'RUB',
    redeemedAt: now,
    payload: { runId }
  }],
  broadcast: {
    campaignId: process.env.OS_SOTA_SMOKE_CAMPAIGN_ID || 'SMOKE_CAMPAIGN_ID',
    platform: process.env.OS_SOTA_SOURCE || process.env.OS_SOTA_PROJECT_SLUG || 'site',
    totals: {
      sent: 10,
      delivered: 9,
      opened: 5,
      clicked: 2,
      unsubscribed: 1,
      failed: 1,
      bounced: 0
    },
    events: [
      { type: 'opened', recipientKey: runId + '-user', email: runId + '@example.com', createdAt: now },
      { type: 'clicked', recipientKey: runId + '-user', url: 'https://example.com/smoke', createdAt: now }
    ]
  },
  aiUsage: [{
    provider: 'openrouter',
    model: 'smoke-model',
    feature: 'smoke-test',
    requests: 1,
    tokens: 123,
    cost: 0.001,
    currency: 'USD',
    status: 'success',
    createdAt: now,
    payload: { runId }
  }],
  marketing: [{
    channel: 'smoke',
    campaign: runId,
    utmSource: 'os-sota-smoke',
    utmCampaign: runId,
    spend: 100,
    leads: 3,
    registrations: 2,
    paidUsers: 1,
    revenue: 1000,
    currency: 'RUB',
    date: now,
    payload: { runId }
  }],
  features: [{
    feature: 'smoke.feature',
    action: 'used',
    userExternalId: runId + '-user',
    sessionId: runId,
    count: 1,
    durationMs: 1000,
    createdAt: now,
    payload: { runId }
  }],
  supportTicket: {
    userEmail: runId + '@example.com',
    userExternalId: runId + '-user',
    title: 'OS SOTA smoke ticket',
    message: 'Тестовое обращение интеграции OS SOTA',
    priority: 'low'
  },
  errors: [{
    level: 'low',
    title: 'OS SOTA smoke error',
    message: 'Тестовая ошибка интеграции',
    status: 'open',
    payload: { runId }
  }],
  documents: [{
    externalId: runId + '-doc',
    title: 'OS SOTA smoke document',
    category: 'integration',
    status: 'active',
    originalName: 'smoke.txt',
    mimeType: 'text/plain',
    fileSize: 10,
    url: 'https://example.com/smoke.txt',
    notes: 'Тестовый документ интеграции',
    createdAt: now,
    payload: { runId }
  }],
  tasks: [{
    externalId: runId + '-task',
    title: 'OS SOTA smoke task',
    description: 'Тестовая задача интеграции',
    status: 'todo',
    priority: 'low',
    dueDate: now,
    progress: 0,
    payload: { runId }
  }]
};

async function main() {
  const config = osSotaConfigStatus();
  const plan = [
    ['metrics', () => sendOsSotaMetrics(samples.metrics)],
    ['users', () => upsertOsSotaUsers(samples.users)],
    ['events', () => sendOsSotaEvents(samples.events)],
    ['payments', () => sendOsSotaPayments(samples.payments)],
    ['subscriptions', () => sendOsSotaSubscriptions(samples.subscriptions)],
    ['promoRedemptions', () => sendOsSotaPromoRedemptions(samples.redemptions)],
    ['aiUsage', () => sendOsSotaAiUsage(samples.aiUsage)],
    ['marketing', () => sendOsSotaMarketingStats(samples.marketing)],
    ['featureUsage', () => sendOsSotaFeatureUsage(samples.features)],
    ['supportTicket', () => sendOsSotaSupportTicket(samples.supportTicket)],
    ['errors', () => sendOsSotaErrors(samples.errors)],
    ['documents', () => sendOsSotaDocuments(samples.documents)],
    ['tasks', () => sendOsSotaTasks(samples.tasks)]
  ];
  if (process.env.OS_SOTA_SMOKE_CAMPAIGN_ID) {
    plan.push(['broadcastStats', () => sendOsSotaBroadcastStats(samples.broadcast)]);
  }

  if (!shouldSend) {
    console.log(JSON.stringify({ mode: 'dry-run', config, runId, endpoints: plan.map(([name]) => name), samples }, null, 2));
    console.log('Dry-run only. Add --send to really post data to OS SOTA.');
    return;
  }

  if (!config.projectSlug || !config.secretConfigured) {
    throw new Error('OS SOTA env is not configured. Fill OS_SOTA_PROJECT_SLUG and OS_SOTA_SYNC_SECRET or OS_SOTA_CORE_API_KEY.');
  }

  const results = [];
  for (const [name, call] of plan) {
    try {
      const response = await call();
      results.push({ name, ok: true, response });
    } catch (error) {
      results.push({ name, ok: false, error: error.message });
    }
  }
  const failed = results.filter((result) => !result.ok);
  console.log(JSON.stringify({ mode: 'send', config, runId, results }, null, 2));
  if (failed.length) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
