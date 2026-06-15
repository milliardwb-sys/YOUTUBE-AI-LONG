import {
  installOsSotaProcessHandlers,
  sendOsSotaMetrics,
  trackOsSotaEvent,
  trackOsSotaError,
  flushOsSotaQueue,
  osSotaConfigStatus
} from './os-sota-core-client.mjs';

export function registerOsSotaRuntimeHooks() {
  installOsSotaProcessHandlers();
}

export function createOsSotaExpressMiddleware(options = {}) {
  const ignore = options.ignore || ['/health', '/favicon.ico'];
  return function osSotaExpressMiddleware(req, res, next) {
    const startedAt = Date.now();
    res.on('finish', () => {
      const path = req.originalUrl || req.url || '';
      if (ignore.some((item) => path.startsWith(item))) return;
      trackOsSotaEvent('http.request', {
        method: req.method,
        path,
        statusCode: res.statusCode,
        durationMs: Date.now() - startedAt,
        userId: req.user?.id || req.userId || null
      }, { safe: true }).catch(() => {});
    });
    next();
  };
}

export function registerOsSotaFastifyHooks(app) {
  app.addHook('onResponse', async (request, reply) => {
    await trackOsSotaEvent('http.request', {
      method: request.method,
      path: request.url,
      statusCode: reply.statusCode,
      durationMs: reply.elapsedTime ?? null,
      userId: request.user?.id || null
    }, { safe: true });
  });
  app.addHook('onError', async (request, reply, error) => {
    await trackOsSotaError(error, {
      source: 'fastify',
      path: request.url,
      method: request.method,
      statusCode: reply.statusCode
    }, { safe: true });
  });
}

export function startOsSotaMetricsHeartbeat(collect, intervalMs = Number(process.env.OS_SOTA_METRICS_INTERVAL_MS || 300000)) {
  if (typeof collect !== 'function') return null;
  const tick = async () => {
    try {
      const metrics = await collect();
      if (metrics) await sendOsSotaMetrics(metrics, { safe: true });
      await flushOsSotaQueue();
    } catch (error) {
      await trackOsSotaError(error, { source: 'metricsHeartbeat' }, { safe: true });
    }
  };
  const timer = setInterval(tick, intervalMs);
  timer.unref?.();
  tick();
  return timer;
}

if (process.argv.includes('--check')) {
  console.log(JSON.stringify({
    config: osSotaConfigStatus(),
    availableHooks: ['runtime', 'express', 'fastify', 'metricsHeartbeat']
  }, null, 2));
}
