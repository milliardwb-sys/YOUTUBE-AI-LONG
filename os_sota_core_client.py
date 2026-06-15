import json
import os
import urllib.error
import urllib.request

DEFAULT_CORE_URL = 'https://os-sota.ru'

def _env(name, fallback=''):
    return os.getenv(name) or fallback

def _headers():
    headers = {'content-type': 'application/json'}
    connector_id = _env('OS_SOTA_CONNECTOR_ID') or _env('CORE_CONNECTOR_ID')
    sync_secret = _env('OS_SOTA_SYNC_SECRET') or _env('CORE_PROJECT_SYNC_SECRET')
    core_api_key = _env('OS_SOTA_CORE_API_KEY') or _env('CORE_API_KEY')
    if connector_id:
        headers['x-connector-id'] = connector_id
    if sync_secret:
        headers['x-project-sync-secret'] = sync_secret
    if core_api_key:
        headers['x-core-api-key'] = core_api_key
    return headers

def _payload(extra=None):
    data = {
        'projectSlug': _env('OS_SOTA_PROJECT_SLUG') or _env('CORE_PROJECT_SLUG'),
        'source': _env('OS_SOTA_SOURCE') or _env('CORE_PROJECT_SLUG') or 'site',
    }
    if extra:
        data.update(extra)
    return data

def os_sota_post(path, payload=None, timeout=15):
    base_url = _env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL).rstrip('/')
    body = json.dumps(_payload(payload or {})).encode('utf-8')
    request = urllib.request.Request(base_url + path, data=body, headers=_headers(), method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode('utf-8')
        raise RuntimeError(f'OS SOTA sync failed: HTTP {error.code} {raw}') from error

def send_os_sota_metrics(payload): return os_sota_post('/connectors/v1/metrics', payload)
def send_os_sota_events(events): return os_sota_post('/connectors/v1/events', {'events': events})
def upsert_os_sota_users(users): return os_sota_post('/connectors/v1/users/upsert', {'users': users})
def send_os_sota_support_ticket(payload): return os_sota_post('/connectors/v1/support/tickets', payload)
def send_os_sota_errors(errors): return os_sota_post('/connectors/v1/errors', {'errors': errors})
def send_os_sota_broadcast_stats(payload): return os_sota_post('/connectors/v1/broadcast/events', payload)
def send_os_sota_payments(payments): return os_sota_post('/connectors/v1/commerce/payments', {'payments': payments})
def send_os_sota_subscriptions(subscriptions): return os_sota_post('/connectors/v1/commerce/subscriptions', {'subscriptions': subscriptions})
def send_os_sota_promo_redemptions(redemptions): return os_sota_post('/connectors/v1/commerce/promo-redemptions', {'redemptions': redemptions})
def send_os_sota_ai_usage(usage): return os_sota_post('/connectors/v1/ai/usage', {'usage': usage})
def send_os_sota_marketing_stats(stats): return os_sota_post('/connectors/v1/marketing/stats', {'stats': stats})
def send_os_sota_feature_usage(features): return os_sota_post('/connectors/v1/features/usage', {'features': features})
def send_os_sota_documents(documents): return os_sota_post('/connectors/v1/documents', {'documents': documents})
def send_os_sota_tasks(tasks): return os_sota_post('/connectors/v1/tasks', {'tasks': tasks})

def os_sota_config_status():
    return {
        'coreUrl': _env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL),
        'projectSlug': _env('OS_SOTA_PROJECT_SLUG') or _env('CORE_PROJECT_SLUG') or None,
        'connectorIdConfigured': bool(_env('OS_SOTA_CONNECTOR_ID') or _env('CORE_CONNECTOR_ID')),
        'secretConfigured': bool(_env('OS_SOTA_SYNC_SECRET') or _env('CORE_PROJECT_SYNC_SECRET') or _env('OS_SOTA_CORE_API_KEY') or _env('CORE_API_KEY')),
    }

if __name__ == '__main__':
    print(json.dumps(os_sota_config_status(), ensure_ascii=False, indent=2))
