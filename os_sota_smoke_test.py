import json
import os
from datetime import datetime, timezone

from os_sota_core_client import (
    os_sota_config_status,
    send_os_sota_metrics,
    send_os_sota_events,
    upsert_os_sota_users,
    send_os_sota_payments,
    send_os_sota_subscriptions,
    send_os_sota_promo_redemptions,
    send_os_sota_ai_usage,
    send_os_sota_marketing_stats,
    send_os_sota_feature_usage,
    send_os_sota_support_ticket,
    send_os_sota_errors,
    send_os_sota_documents,
    send_os_sota_tasks,
    send_os_sota_broadcast_stats,
)

def main(send=False):
    now = datetime.now(timezone.utc).isoformat()
    run_id = 'smoke-' + str(int(datetime.now().timestamp() * 1000))
    email = run_id + '@example.com'
    samples = {
        'metrics': {'users': 12, 'newUsers': 2, 'activeUsers': 7, 'revenue': 1000, 'expenses': 250, 'ticketsOpen': 1, 'ticketsClosed': 0, 'apiCost': 0.12, 'currency': 'RUB', 'apiCurrency': 'USD'},
        'users': [{'externalId': run_id + '-user', 'email': email, 'name': 'OS SOTA Smoke User', 'status': 'active', 'registered': True, 'onboardingDone': True, 'firstActionDone': True, 'paymentDone': True, 'secondVisitDone': False}],
        'events': [{'eventType': 'smoke.product_event', 'userExternalId': run_id + '-user', 'sessionId': run_id, 'page': '/smoke', 'payload': {'runId': run_id}, 'createdAt': now}],
        'payments': [{'externalPaymentId': run_id + '-payment', 'userExternalId': run_id + '-user', 'userEmail': email, 'amount': 1000, 'currency': 'RUB', 'status': 'paid', 'provider': 'os-sota-smoke', 'tariffCode': 'SMOKE', 'promoCode': 'SMOKE10', 'paidAt': now, 'payload': {'runId': run_id}}],
        'subscriptions': [{'externalId': run_id + '-subscription', 'userExternalId': run_id + '-user', 'userEmail': email, 'tariffCode': 'SMOKE', 'status': 'active', 'startsAt': now, 'limits': {'generations': 10}, 'usage': {'generations': 1}, 'payload': {'runId': run_id}}],
        'redemptions': [{'code': 'SMOKE10', 'userExternalId': run_id + '-user', 'userEmail': email, 'orderId': run_id + '-order', 'discountAmount': 100, 'currency': 'RUB', 'redeemedAt': now, 'payload': {'runId': run_id}}],
        'aiUsage': [{'provider': 'openrouter', 'model': 'smoke-model', 'feature': 'smoke-test', 'requests': 1, 'tokens': 123, 'cost': 0.001, 'currency': 'USD', 'status': 'success', 'createdAt': now, 'payload': {'runId': run_id}}],
        'marketing': [{'channel': 'smoke', 'campaign': run_id, 'utmSource': 'os-sota-smoke', 'utmCampaign': run_id, 'spend': 100, 'leads': 3, 'registrations': 2, 'paidUsers': 1, 'revenue': 1000, 'currency': 'RUB', 'date': now, 'payload': {'runId': run_id}}],
        'features': [{'feature': 'smoke.feature', 'action': 'used', 'userExternalId': run_id + '-user', 'sessionId': run_id, 'count': 1, 'durationMs': 1000, 'createdAt': now, 'payload': {'runId': run_id}}],
        'supportTicket': {'userEmail': email, 'userExternalId': run_id + '-user', 'title': 'OS SOTA smoke ticket', 'message': 'Тестовое обращение интеграции OS SOTA', 'priority': 'low'},
        'errors': [{'level': 'low', 'title': 'OS SOTA smoke error', 'message': 'Тестовая ошибка интеграции', 'status': 'open', 'payload': {'runId': run_id}}],
        'documents': [{'externalId': run_id + '-doc', 'title': 'OS SOTA smoke document', 'category': 'integration', 'status': 'active', 'originalName': 'smoke.txt', 'mimeType': 'text/plain', 'fileSize': 10, 'url': 'https://example.com/smoke.txt', 'notes': 'Тестовый документ интеграции', 'createdAt': now, 'payload': {'runId': run_id}}],
        'tasks': [{'externalId': run_id + '-task', 'title': 'OS SOTA smoke task', 'description': 'Тестовая задача интеграции', 'status': 'todo', 'priority': 'low', 'dueDate': now, 'progress': 0, 'payload': {'runId': run_id}}],
    }
    plan = [
        ('metrics', lambda: send_os_sota_metrics(samples['metrics'])),
        ('users', lambda: upsert_os_sota_users(samples['users'])),
        ('events', lambda: send_os_sota_events(samples['events'])),
        ('payments', lambda: send_os_sota_payments(samples['payments'])),
        ('subscriptions', lambda: send_os_sota_subscriptions(samples['subscriptions'])),
        ('promoRedemptions', lambda: send_os_sota_promo_redemptions(samples['redemptions'])),
        ('aiUsage', lambda: send_os_sota_ai_usage(samples['aiUsage'])),
        ('marketing', lambda: send_os_sota_marketing_stats(samples['marketing'])),
        ('featureUsage', lambda: send_os_sota_feature_usage(samples['features'])),
        ('supportTicket', lambda: send_os_sota_support_ticket(samples['supportTicket'])),
        ('errors', lambda: send_os_sota_errors(samples['errors'])),
        ('documents', lambda: send_os_sota_documents(samples['documents'])),
        ('tasks', lambda: send_os_sota_tasks(samples['tasks'])),
    ]
    if os.getenv('OS_SOTA_SMOKE_CAMPAIGN_ID'):
        plan.append(('broadcastStats', lambda: send_os_sota_broadcast_stats({'campaignId': os.getenv('OS_SOTA_SMOKE_CAMPAIGN_ID'), 'platform': os.getenv('OS_SOTA_SOURCE') or os.getenv('OS_SOTA_PROJECT_SLUG') or 'site', 'totals': {'sent': 10, 'delivered': 9, 'opened': 5, 'clicked': 2, 'unsubscribed': 1, 'failed': 1, 'bounced': 0}})))

    config = os_sota_config_status()
    if not send:
        print(json.dumps({'mode': 'dry-run', 'config': config, 'runId': run_id, 'endpoints': [name for name, _ in plan], 'samples': samples}, ensure_ascii=False, indent=2))
        print('Dry-run only. Add --send to really post data to OS SOTA.')
        return
    if not config.get('projectSlug') or not config.get('secretConfigured'):
        raise RuntimeError('OS SOTA env is not configured.')
    results = []
    for name, call in plan:
        try:
            results.append({'name': name, 'ok': True, 'response': call()})
        except Exception as error:
            results.append({'name': name, 'ok': False, 'error': str(error)})
    print(json.dumps({'mode': 'send', 'config': config, 'runId': run_id, 'results': results}, ensure_ascii=False, indent=2))
    if any(not item['ok'] for item in results):
        raise SystemExit(1)

if __name__ == '__main__':
    import sys
    main('--send' in sys.argv)
