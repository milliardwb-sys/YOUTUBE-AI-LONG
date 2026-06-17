# Mobile MVP v0.4

Минимальный Expo-клиент для backend `AI Video Studio MVP`.

Что умеет:

- создать проект;
- выбрать режим источников;
- включить/выключить OpenAI LLM-сценарист;
- включить/выключить OpenAI TTS;
- включить/выключить burned subtitles flag;
- запустить `generate_all` как backend job;
- опрашивать `GET /jobs/{job_id}`;
- отменить активную job через `POST /jobs/{job_id}/cancel`;
- повторить failed/cancelled job через `POST /jobs/{job_id}/retry`;
- войти или зарегистрироваться через backend auth, если включён `ENABLE_USER_AUTH=true`;
- загрузить список проектов через `GET /projects`;
- открыть старый проект и его readiness manifest;
- редактировать сцены: title, narration, duration;
- добавлять, удалять и регенерировать slide для выбранной сцены;
- показать progress, статус, warnings, источники, сцены и ссылки на результат.

Запуск:

```bash
cd mobile
npm install
npm start
```

Backend должен работать на:

```text
http://localhost:8000
```

Настройки клиента задаются через Expo public env:

```text
EXPO_PUBLIC_API_BASE_URL=http://localhost:8000
EXPO_PUBLIC_API_KEY=
```

На физическом телефоне используйте IP компьютера в локальной сети: `EXPO_PUBLIC_API_BASE_URL=http://<LAN_IP>:8000`. Если backend запущен с `API_KEY`, тот же ключ нужно передать в `EXPO_PUBLIC_API_KEY`.

Если backend запущен с `ENABLE_USER_AUTH=true`, используйте блок `Account` в приложении. После login/register клиент добавляет `Authorization: Bearer <token>` ко всем project/job/file API requests. Logout вызывает `/auth/logout`, отзывает backend session и очищает локальный token. Bearer token не задаётся через Expo env и живёт только в текущей сессии приложения.

Проверки:

```bash
npm run check:ci
npm run audit:strict
```

`check:ci` падает только на high/critical production advisories и запускает TypeScript. `audit:strict` показывает также moderate advisories. На текущем Expo/React Native стеке npm может показывать moderate `js-yaml` advisory в Metro/Jest dependency chain; автоматический fix требует breaking upgrade React Native, поэтому его нужно делать отдельным upgrade-этапом.
