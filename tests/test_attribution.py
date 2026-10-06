import io
import zipfile
import pytest

from app.db import get_db, init_db
from app.services.reporting import report, export_zip
from conftest import Participant, rows
from test_seed import seed_person


@pytest.mark.parametrize('query,expected', [('?src=' + s, s) for s in
    ('slack', 'everytime', 'dc', 'arca', 'threads', 'instagram')] + [('', 'direct'),
    ('?src=whatever', 'direct'), ('?src=%20SLACK%20', 'slack')])
def test_first_touch_and_no_extra_events(app, query, expected):
    client = app.test_client()
    response = client.get('/' + query, follow_redirects=True)
    assert response.status_code == 200
    assert rows(app, 'visitor_attributions')[0]['source'] == expected
    assert len(rows(app, 'page_views')) == 1
    assert rows(app, 'events') == []
    client.get('/?src=instagram', follow_redirects=True)
    assert rows(app, 'visitor_attributions')[0]['source'] == expected
    assert len(rows(app, 'page_views')) == 2
    assert rows(app, 'events') == []


def sourced_person(app, source):
    p = Participant.__new__(Participant)
    p.app, p.client, p.sequence = app, app.test_client(), 0
    p.client.get('/?src=' + source, follow_redirects=True)
    p.open(landing=True)
    p.open()
    return p


def test_source_funnel_cohorts_and_kpi_preservation(app):
    a, b = sourced_person(app, 'slack'), sourced_person(app, 'slack')
    direct = sourced_person(app, 'whatever')
    a.action('emoji', option_id='0')
    a.action('poll', option_id='0')
    a.action('short', body='감상')
    b.action('observe', event_type='community_open')
    b.expose(a.state()['own_reviews']['short']['id'])
    a.open('little-prince')
    a.action('emoji', option_id='0')
    with app.app_context():
        baseline = report()
    seed = seed_person(app)
    seed.client.get('/?src=threads', follow_redirects=True)
    seed.open(landing=True)
    seed.open()
    seed.action('emoji', option_id='0')
    app.config['TESTING'] = False
    test = sourced_person(app, 'slack')
    test.action('emoji', option_id='0')
    with app.app_context():
        data = report()
        assert data['scopes'] == baseline['scopes']
        assert data['judgment'] == baseline['judgment']
        assert data['sources'] == baseline['sources']
        slack = next(r for r in data['sources'] if r['source'] == 'slack')
        assert slack['landing'] == slack['book_view'] == 2
        assert [m['numerator'] for m in slack['metrics']] == [1, 1, 1, 1]
        assert all(m['ratio'] == .5 for m in slack['metrics'])
        assert sum(r['landing'] for r in data['sources']) == data['landing']['unique'] == 3
        assert sum(r['book_view'] for r in data['sources']) == data['scopes']['all']['visitors'] == 3
        assert next(r for r in data['sources'] if r['source'] == 'dc')['metrics'][0]['ratio'] is None
        archive = zipfile.ZipFile(io.BytesIO(export_zip()))
        csv = archive.read('visitor_sources.csv').decode('utf-8-sig')
        assert a.visitor_id() in csv and direct.visitor_id() in csv
        assert seed.visitor_id() not in csv and test.visitor_id() not in csv
        assert 'csrf_token' not in csv and 'token_hash' not in csv
        # Removing attribution simulates the historical schema, without reclassifying old visitors.
        get_db().execute('DROP TABLE visitor_attributions')
        snapshot = {name: rows(app, name) for name in ('visitors', 'events', 'reviews', 'seed_participants', 'seed_invites')}
        init_db()
        init_db()
        assert snapshot == {name: rows(app, name) for name in snapshot}
        assert rows(app, 'visitor_attributions') == []
        historical = report()
        assert historical['scopes'] == baseline['scopes']
        assert next(r for r in historical['sources'] if r['source'] == 'direct')['book_view'] == 3
    a.client.get('/?src=instagram', follow_redirects=True)
    assert rows(app, 'visitor_attributions') == []
