import json
import os
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_CORE_URL = 'https://os-sota.ru'
DEFAULT_QUEUE_FILE = '.os-sota-sync-queue.jsonl'

def _env(name, fallback=''):
    return os.getenv(name) or fallback

def _now():
    return datetime.now(timezone.utc).isoformat()

def _bool_env(name, fallback=True):
    value = _env(name)
    if not value:
        return fallback
    return str(value).lower() not in ['0', 'false', 'off', 'no']

def _queue_file():
    return _env('OS_SOTA_QUEUE_FILE', DEFAULT_QUEUE_FILE)

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

def _project_slug():
    return _env('OS_SOTA_PROJECT_SLUG') or _env('CORE_PROJECT_SLUG')

def _source():
    return _env('OS_SOTA_SOURCE') or _project_slug() or 'site'

def _configured():
    return bool(_project_slug() and (_env('OS_SOTA_SYNC_SECRET') or _env('CORE_PROJECT_SYNC_SECRET') or _env('OS_SOTA_CORE_API_KEY') or _env('CORE_API_KEY')))

def _payload(extra=None):
    data = {
        'projectSlug': _project_slug(),
        'source': _source(),
        'environment': _env('PYTHON_ENV') or _env('ENV') or 'production',
        'sourceVersion': _env('OS_SOTA_SOURCE_VERSION') or None,
        'sentAt': _now(),
    }
    if extra:
        data.update(extra)
    return data

def enqueue_os_sota(path, payload, reason=''):
    if not _bool_env('OS_SOTA_QUEUE_ENABLED', True):
        return {'queued': False, 'reason': 'queue disabled'}
    item = {'path': path, 'payload': payload, 'reason': reason, 'attempts': 0, 'createdAt': _now()}
    with open(_queue_file(), 'a', encoding='utf-8') as file:
        file.write(json.dumps(item, ensure_ascii=False) + '\n')
    return {'queued': True}

def os_sota_post(path, payload=None, timeout=15, safe=False, queue_on_fail=True):
    body_payload = _payload(payload or {})
    if not _bool_env('OS_SOTA_ENABLE_SYNC', True):
        return {'ok': False, 'skipped': True, 'reason': 'OS_SOTA_ENABLE_SYNC is disabled'}
    if not _configured():
        reason = 'OS SOTA env is not configured'
        if safe:
            return {'ok': False, 'skipped': True, 'reason': reason}
        raise RuntimeError(reason)
    base_url = _env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL).rstrip('/')
    body = json.dumps(body_payload).encode('utf-8')
    request = urllib.request.Request(base_url + path, data=body, headers=_headers(), method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else None
    except Exception as error:
        if queue_on_fail:
            enqueue_os_sota(path, body_payload, str(error))
        if safe:
            return {'ok': False, 'queued': queue_on_fail, 'error': str(error)}
        raise

def flush_os_sota_queue():
    file_name = _queue_file()
    if not os.path.exists(file_name):
        return {'ok': True, 'flushed': 0, 'failed': 0, 'remaining': 0}
    with open(file_name, 'r', encoding='utf-8') as file:
        items = [json.loads(line) for line in file if line.strip()]
    failed = []
    flushed = 0
    for item in items:
        try:
            os_sota_post(item['path'], item.get('payload') or {}, queue_on_fail=False)
            flushed += 1
        except Exception as error:
            item['attempts'] = int(item.get('attempts') or 0) + 1
            item['reason'] = str(error)
            item['lastAttemptAt'] = _now()
            failed.append(item)
    if failed:
        with open(file_name, 'w', encoding='utf-8') as file:
            for item in failed:
                file.write(json.dumps(item, ensure_ascii=False) + '\n')
    else:
        os.remove(file_name)
    return {'ok': len(failed) == 0, 'flushed': flushed, 'failed': len(failed), 'remaining': len(failed)}

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

def safe_os_sota_post(path, payload=None): return os_sota_post(path, payload or {}, safe=True, queue_on_fail=True)
def os_sota_get(path, query=None, safe=False):
    if not _bool_env('OS_SOTA_ENABLE_SYNC', True):
        return {'ok': False, 'skipped': True, 'reason': 'OS_SOTA_ENABLE_SYNC is disabled'}
    if not _configured():
        reason = 'OS SOTA env is not configured'
        if safe:
            return {'ok': False, 'skipped': True, 'reason': reason}
        raise RuntimeError(reason)
    params = {'projectSlug': _project_slug() or '', 'source': _source()}
    if query:
        params.update(query)
    from urllib.parse import urlencode
    request = urllib.request.Request(_env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL).rstrip('/') + path + '?' + urlencode(params), headers=_headers(), method='GET')
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else None
    except Exception as error:
        if safe:
            return {'ok': False, 'error': str(error)}
        raise

def pull_os_sota_config(safe=False): return os_sota_get('/connectors/v1/config', safe=safe)
def track_os_sota_event(event_type, payload=None): return safe_os_sota_post('/connectors/v1/events', {'events': [{'eventType': event_type, 'payload': payload or {}, 'createdAt': _now()}]})
def track_os_sota_error(error, payload=None):
    return safe_os_sota_post('/connectors/v1/errors', {'errors': [{'level': (payload or {}).get('level', 'high'), 'title': error.__class__.__name__, 'message': str(error), 'status': 'open', 'payload': payload or {}}]})

def install_os_sota_exception_hook():
    import sys
    previous = sys.excepthook
    def hook(exc_type, exc, tb):
        try:
            track_os_sota_error(exc, {'source': 'sys.excepthook', 'traceback': ''.join(traceback.format_exception(exc_type, exc, tb)), 'level': 'critical'})
        finally:
            previous(exc_type, exc, tb)
    sys.excepthook = hook

def os_sota_config_status():
    return {
        'coreUrl': _env('OS_SOTA_CORE_URL', DEFAULT_CORE_URL),
        'projectSlug': _project_slug() or None,
        'source': _source(),
        'connectorIdConfigured': bool(_env('OS_SOTA_CONNECTOR_ID') or _env('CORE_CONNECTOR_ID')),
        'secretConfigured': bool(_env('OS_SOTA_SYNC_SECRET') or _env('CORE_PROJECT_SYNC_SECRET') or _env('OS_SOTA_CORE_API_KEY') or _env('CORE_API_KEY')),
        'queueFile': _queue_file(),
        'queueEnabled': _bool_env('OS_SOTA_QUEUE_ENABLED', True),
        'syncEnabled': _bool_env('OS_SOTA_ENABLE_SYNC', True),
    }

if __name__ == '__main__':
    import sys
    if '--flush' in sys.argv:
        print(json.dumps(flush_os_sota_queue(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(os_sota_config_status(), ensure_ascii=False, indent=2))
