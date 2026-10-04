from itsdangerous import URLSafeTimedSerializer

from app.services.reporting import report
from conftest import Participant, rows

AUTH = {'Authorization': 'Basic YWRtaW46dGVzdC1wYXNzd29yZA=='}


def test_production_ignores_legacy_admin_cookie_without_reclassifying_visitors(app):
    app.config['LOCAL_DEVELOPMENT'] = False
    app.config['TESTING'] = False
    client = app.test_client()
    token = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='visitor-cookie').dumps('admin')
    client.set_cookie('admin_test', token)
    assert client.get('/admin/', headers=AUTH, base_url='https://localhost').status_code == 200
    assert client.get('/books/metamorphosis', follow_redirects=True, base_url='https://localhost').status_code == 200
    visitor = rows(app, 'visitors')[0]
    assert visitor['is_test'] == 0 and visitor['exclusion_reason'] is None
    assert client.get('/admin/export', headers=AUTH, base_url='https://localhost').status_code == 200
    assert rows(app, 'visitors')[0]['is_test'] == 0


def test_dashboard_preserves_report_values_and_details(app):
    a, b = Participant(app), Participant(app)
    a.action('emoji', option_id='0')
    a.action('poll', option_id='1')
    a.action('short', body='a short')
    b.action('observe', event_type='community_open')
    b.expose(a.state()['own_reviews']['short']['id'])
    b.action('like', target_id=a.state()['own_reviews']['short']['id'], active=True)
    b.action('reply', target_id=a.state()['own_reviews']['short']['id'], body='reply')
    b.open('little-prince')
    with app.app_context():
        before = report()
    response = a.client.get('/admin/', headers=AUTH)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('class="kpi"') == 5
    assert html.count('class="book-dashboard-card"') == 3
    assert '테스트 visitor 전용 집계' not in html and '<table' not in html
    assert '목표 30%' in html and '목표 10%' in html and '최소 표본 50명' in html
    assert '50.0%' in html and 'CSV Export (.zip)' in html
    for scope, data in before['scopes'].items():
        for metric in data['metrics']:
            assert metric['label'] in html
        for event in data['events']:
            assert event['name'] in html
    with app.app_context():
        assert report()['scopes'] == before['scopes']
    assert a.client.get_cookie('admin_test') is None


def test_dashboard_empty_denominators_are_na_and_test_only_data_excluded(app):
    app.config['TESTING'] = False
    p = Participant(app)
    p.action('emoji', option_id='0')
    response = p.client.get('/admin/', headers=AUTH)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'N/A' in html and '0 / 0명' in html
    with app.app_context():
        assert report()['scopes']['all']['visitors'] == 0
    assert rows(app, 'visitors')[0]['is_test'] == 1
