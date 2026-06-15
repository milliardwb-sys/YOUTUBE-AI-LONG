# ТЗ интеграции с OS SOTA CORE: ai-video-studio-mobile-stub

## 1. Цель
Подключить проект `ai-video-studio-mobile-stub` к единому центру управления OS SOTA, чтобы командный центр видел метрики, пользователей, события, поддержку, ошибки и статистику рассылок.

## 2. Данные проекта
- Локальный путь: `C:/Users/user/Documents/YOUTUBE AI VIDEO STUDIO/ai-video-studio-mvp`
- Рекомендуемый slug: `ai-video-studio-mobile-stub`
- Тип кода: `node-python`
- CORE URL: `https://os-sota.ru`

## 3. Env-настройки
Добавить значения из `OS_SOTA_INTEGRATION.env.example` в production env проекта.

Важно: `OS_SOTA_SYNC_SECRET` нельзя хранить во frontend-коде. Его можно использовать только на backend/server/worker стороне.

## 4. Что проект отправляет в CORE
1. `POST /connectors/v1/metrics` каждые 5-15 минут: пользователи, активные пользователи, выручка, расходы, тикеты, API-затраты.
2. `POST /connectors/v1/users/upsert` сразу после регистрации или изменения пользователя.
3. `POST /connectors/v1/events` сразу или пачкой до 500 событий: регистрации, визиты, действия, конверсии.
4. `POST /connectors/v1/support/tickets` при новом обращении в поддержку.
5. `POST /connectors/v1/errors` при критической ошибке, падении job или проблеме интеграции.
6. `POST /connectors/v1/broadcast/events` после рассылки или пачкой: отправлено, доставлено, открытия, клики, отписки, ошибки, bounce.

## 5. Что проект должен принимать из CORE
В проекте нужно добавить backend endpoint `POST /os-sota/webhook` или аналогичный route и указать его как `webhookUrl` в OS SOTA.

Endpoint должен принимать события:
- `tariff.updated` и `tariff.deleted` — создать, обновить или отключить тариф на платформе.
- `promo.updated` и `promo.deleted` — создать, обновить или отключить промокод.
- `broadcast.created` — поставить рассылку в локальную очередь платформы.

## 6. Минимальный код уже добавлен
- `OS_SOTA_INTEGRATION.env.example`
- `os-sota-core-client.mjs`
- `os_sota_core_client.py`

- `os-sota-smoke-test.mjs`
- `os_sota_smoke_test.py`

## 7. Пример отправки статистики рассылки
```js
import { sendOsSotaBroadcastStats } from './os-sota-core-client.mjs';

await sendOsSotaBroadcastStats({
  campaignId: 'CAMPAIGN_ID_FROM_CORE',
  platform: 'ai-video-studio-mobile-stub',
  totals: {
    sent: 1000,
    delivered: 960,
    opened: 540,
    clicked: 126,
    unsubscribed: 8,
    failed: 25,
    bounced: 15
  },
  events: [
    {
      type: 'opened',
      recipientKey: 'user_123',
      email: 'client@example.com',
      createdAt: new Date().toISOString()
    },
    {
      type: 'clicked',
      recipientKey: 'user_123',
      url: 'https://example.com/pro',
      createdAt: new Date().toISOString()
    }
  ]
});
```

## 8. Полный DATA CONTRACT v1
В проект можно подключать максимум данных через готовые методы клиента:

### Операционные метрики
- `sendOsSotaMetrics(payload)` -> `/connectors/v1/metrics`
- `sendOsSotaEvents(events)` -> `/connectors/v1/events`
- `sendOsSotaFeatureUsage(features)` -> `/connectors/v1/features/usage`

### Пользователи и доступ
- `upsertOsSotaUsers(users)` -> `/connectors/v1/users/upsert`
- `sendOsSotaSubscriptions(subscriptions)` -> `/connectors/v1/commerce/subscriptions`

### Деньги и коммерция
- `sendOsSotaPayments(payments)` -> `/connectors/v1/commerce/payments`
- `sendOsSotaPromoRedemptions(redemptions)` -> `/connectors/v1/commerce/promo-redemptions`
- `sendOsSotaBroadcastStats(payload)` -> `/connectors/v1/broadcast/events`

### AI, маркетинг и поддержка
- `sendOsSotaAiUsage(usage)` -> `/connectors/v1/ai/usage`
- `sendOsSotaMarketingStats(stats)` -> `/connectors/v1/marketing/stats`
- `sendOsSotaSupportTicket(payload)` -> `/connectors/v1/support/tickets`
- `sendOsSotaErrors(errors)` -> `/connectors/v1/errors`

### Документы и задачи
- `sendOsSotaDocuments(documents)` -> `/connectors/v1/documents`
- `sendOsSotaTasks(tasks)` -> `/connectors/v1/tasks`

## 9. Критерии готовности
- В OS SOTA создан проект и connector для `ai-video-studio-mobile-stub`.
- В env проекта внесены `OS_SOTA_PROJECT_SLUG`, `OS_SOTA_CONNECTOR_ID`, `OS_SOTA_SYNC_SECRET`.
- Проверка env проходит.
- Dry-run smoke показывает payload без ошибок.
- Smoke с `--send` отправляет тестовые данные в OS SOTA.
- Метрики появляются в командном центре.
- Тарифы, промокоды и рассылки из CORE применяются на платформе.
- Статистика рассылок отображает открытия, клики, отписки и ошибки по платформе.

## 10. Как тестировать интеграцию
1. Создать/проверить проект и connector в OS SOTA.
2. Заполнить env из `OS_SOTA_INTEGRATION.env.example`.
3. Выполнить dry-run:
   ```bash
   node os-sota-smoke-test.mjs
   ```
4. Выполнить реальную отправку:
   ```bash
   node os-sota-smoke-test.mjs --send
   ```
5. В OS SOTA проверить:
   - обновился статус connector;
   - появились SyncRun;
   - появились метрики/события/платежи/AI usage/маркетинг/задачи/документы;
   - нет ошибок авторизации или HMAC.


## 11. Production слой, добавленный Codex

В проект добавлен production-слой интеграции:

- `os-sota-core-client.mjs` / `os_sota_core_client.py` теперь умеет не только отправлять данные, но и безопасно складывать их в локальную очередь `.os-sota-sync-queue.jsonl`, если OS SOTA временно недоступен.
- `npm run os-sota:flush` повторно отправляет накопленную очередь.
- `os-sota-auto-hooks.mjs` добавляет готовые hooks для Express/Fastify, runtime errors и heartbeat метрик.
- Все реальные бизнес-события проекта надо подключать через safe-методы, чтобы основной продукт не падал из-за недоступности командного центра.

Минимальная врезка в Node/Express:

```js
import { createOsSotaExpressMiddleware, registerOsSotaRuntimeHooks } from './os-sota-auto-hooks.mjs';

registerOsSotaRuntimeHooks();
app.use(createOsSotaExpressMiddleware());
```

Пример бизнес-события:

```js
import { trackOsSotaEvent, trackOsSotaPayment, trackOsSotaAiUsage } from './os-sota-core-client.mjs';

await trackOsSotaEvent('lead.created', { leadId, source: 'telegram' }, { safe: true });
await trackOsSotaPayment({ externalPaymentId, amount, currency: 'RUB', status: 'paid' }, { safe: true });
await trackOsSotaAiUsage({ provider: 'openrouter', model, feature: 'generation', tokens, cost }, { safe: true });
```
