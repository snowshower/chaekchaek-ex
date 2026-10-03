from uuid import uuid4

import pytest

from app.db import get_db
from app.services.reporting import report
from conftest import Participant


def metric(data,name,scope='all'):
    return next(m for m in data['scopes'][scope]['metrics'] if m['metric_name']==name)


def test_zero_denominator_landing_only(app):
    person = Participant(app)
    with app.app_context():
        get_db().execute('DELETE FROM events')
    person.open(landing=True)
    with app.app_context():
        data = report()
        assert data['landing']['unique'] == 1
        assert data['scopes']['all']['visitors'] == 0
        assert metric(data,'light_participation')['ratio'] is None
        assert data['judgment'] == '판정 불가'


def test_main_union_historical_success_and_book_union(app):
    people = [Participant(app) for _ in range(10)]
    for person in people[:4]: person.action('emoji',option_id='0')
    for person in people[2:5]: person.action('poll',option_id='0')
    people[0].action('short',body='짧은 글')
    people[0].action('short',delete=True)
    people[0].action('emoji',option_id=None)
    people[0].open('little-prince')
    people[0].action('emoji',option_id='1')
    with app.app_context():
        data = report()
        assert data['scopes']['all']['visitors'] == 10
        assert data['scopes']['metamorphosis']['visitors'] == 10
        assert data['scopes']['little-prince']['visitors'] == 1
        assert metric(data,'light_participation')['numerator'] == 5
        assert metric(data,'light_participation')['ratio'] == .5
        assert metric(data,'text_participation')['ratio'] == .1
        assert data['judgment'] == '판정 불가'


@pytest.mark.parametrize('visitors,light,short,reliable,expected',[(49,15,5,True,'판정 불가'),(50,15,5,True,'검증'),(50,14,5,True,'기각'),(50,15,4,True,'기각'),(50,15,5,False,'판정 불가')])
def test_sample_threshold_exact_unrounded(app,visitors,light,short,reliable,expected):
    # Insert immutable source events directly to isolate arithmetic boundaries from HTTP behavior.
    with app.app_context():
        db = get_db()
        for index in range(visitors):
            visitor,page = str(uuid4()),str(uuid4())
            db.execute('INSERT INTO visitors VALUES (?,?,?,0,NULL,?)',(visitor,'2026-01-01T00:00:00.000000Z','[]','csrf'))
            db.execute('INSERT INTO page_views VALUES (?,?,?,?,NULL,NULL,?)',(page,visitor,'metamorphosis','metamorphosis-v1','2026-01-01T00:00:00.000000Z'))
            names = ['book_view'] + (['emoji_reaction'] if index<light else []) + (['short_review_submit'] if index<short else [])
            for sequence,name in enumerate(names,1):
                db.execute('INSERT INTO events (event_id,visitor_id,event_type,timestamp,page_view_id,book_id,content_version_id,exposure_context,client_occurred_at,client_sequence) VALUES (?,?,?,?,?,?,?,?,?,?)',(str(uuid4()),visitor,name,'2026-01-01T00:00:00.000000Z',page,'metamorphosis','metamorphosis-v1','{}','2026-01-01T00:00:00Z',sequence))
        app.config['DATA_RELIABLE'] = reliable
        assert report()['judgment'] == expected


def test_interaction_same_book_after_exposure_union(app):
    writer = Participant(app)
    writer.action('short',body='원글')
    target = writer.state()['own_reviews']['short']['id']
    a,b,c = [Participant(app) for _ in range(3)]
    for p in (a,b,c): p.action('observe',event_type='community_open')
    a.action('like',target_id=target,active=True)  # Prior to exposure: excluded.
    a.expose(target)
    b.expose(target)
    b.action('like',target_id=target,active=True)
    b.action('reply',target_id=target,body='답글')
    b.action('like',target_id=target,active=False)
    c.open('little-prince')
    c.action('observe',event_type='community_open')
    # Exposure on another book must not qualify c's interactions here.
    writer.open('little-prince'); writer.action('short',body='다른 책 원글')
    other_target = writer.state()['own_reviews']['short']['id']
    c.expose(other_target)
    c.open(); c.action('reply',target_id=target,body='선행 노출 없는 답글')
    b.open(); b.action('reply',target_id=target,body='자동 복원, 이전 방문 선행 노출')
    with app.app_context():
        data = report()
        assert metric(data,'interaction','metamorphosis')['numerator'] == 1
        assert metric(data,'interaction','metamorphosis')['denominator'] == 2
        assert metric(data,'interaction')['numerator'] == 1
        assert metric(data,'interaction')['denominator'] == 3
        assert metric(data,'community_direct')['numerator'] == 3


def test_period_start_inclusive_end_exclusive_and_test_retroactive(app):
    person = Participant(app)
    person.action('emoji',option_id='0')
    with app.app_context():
        db = get_db()
        db.execute("UPDATE events SET timestamp='2026-01-01T00:00:00.000000Z' WHERE event_type='book_view'")
        db.execute("UPDATE events SET timestamp='2026-02-01T00:00:00.000000Z' WHERE event_type='emoji_reaction'")
        app.config['EXPERIMENT_START']='2026-01-01T00:00:00.000000Z'
        app.config['EXPERIMENT_END']='2026-02-01T00:00:00.000000Z'
        data=report()
        assert data['scopes']['all']['visitors']==1
        assert metric(data,'light_participation')['numerator']==0
        db.execute('UPDATE visitors SET is_test=1,exclusion_reason=?',('retroactive',))
        assert report()['scopes']['all']['visitors']==0


def test_same_page_client_order_overrides_network_arrival_order(app):
    writer=Participant(app)
    writer.action('short',body='원글')
    person=Participant(app)
    person.action('short',body='먼저 쓴 감상')
    person.action('observe',event_type='community_open')
    person.expose(writer.state()['own_reviews']['short']['id'])
    person.action('like',target_id=writer.state()['own_reviews']['short']['id'],active=True)
    with app.app_context():
        db=get_db()
        db.execute("UPDATE events SET timestamp='2026-09-30T01:00:00.000000Z',short_submitted_before=0 WHERE visitor_id=? AND event_type IN ('community_open','like')",(person.visitor_id(),))
        db.execute("UPDATE events SET timestamp='2026-09-30T02:00:00.000000Z' WHERE visitor_id=? AND event_type IN ('short_review_submit','others_reveal')",(person.visitor_id(),))
        data=report()
        assert metric(data,'community_after_short')['numerator']==1
        assert metric(data,'community_without_short')['numerator']==0
        assert metric(data,'interaction')['numerator']==1
        assert data['quality']['client_order_arrival_mismatch']>0


def test_development_data_is_separate_and_preserves_history(app):
    from app.services.reporting import test_report as development_report
    actual = Participant(app)
    actual.action('short', body='actual')
    target = actual.state()['own_reviews']['short']['id']
    with app.app_context():
        before = report()
    app.config['TESTING'] = False
    # Retroactively exclude the writer, then create a real baseline visitor.
    with app.app_context():
        get_db().execute('UPDATE visitors SET is_test=1 WHERE visitor_id=?', (actual.visitor_id(),))
    app.config['TESTING'] = True
    actual = Participant(app)
    with app.app_context():
        before = report()
    app.config['TESTING'] = False
    dev = Participant(app)
    dev.action('emoji', option_id='0')
    dev.action('poll', option_id='1')
    dev.action('short', body='development')
    dev.action('observe', event_type='community_open')
    dev.expose(target)
    dev.expose(target)
    dev.action('like', target_id=target, active=True)
    dev.action('reply', target_id=target, body='test reply')
    dev.action('full', body='test full')
    dev.action('emoji', option_id=None)
    dev.action('short', delete=True)
    dev.action('like', target_id=target, active=False)
    dev.open('little-prince')
    dev.action('poll', option_id='0')
    with app.app_context():
        after = report()
        assert after['scopes'] == before['scopes']
        assert after['sample_met'] == before['sample_met']
        assert after['judgment'] == before['judgment']
        data = development_report()
        assert 'judgment' not in data and 'sample_met' not in data
        assert data['scopes']['all']['visitors'] == 2
        assert data['scopes']['little-prince']['visitors'] == 1
        for name in ('light_participation', 'text_participation', 'community_direct', 'others_exposure', 'interaction', 'full_participation'):
            m = metric(data, name, 'metamorphosis')
            assert m['numerator'] == (2 if name == 'text_participation' else 1)
            assert m['denominator'] == (1 if name == 'interaction' else 2)
        current = data['scopes']['metamorphosis']['current']
        assert current['emoji'] == current['likes'] == 0
        assert current['short_reviews'] == 1
        assert current['poll'] == current['full_reviews'] == current['replies'] == 1
    actual.action('emoji', option_id='2')
    actual.action('poll', option_id='2')
    actual.action('observe', event_type='community_open')
    public = actual.state()
    assert sum(x['count'] for x in public['emoji_results']) == 1
    assert sum(x['count'] for x in public['poll_results']) == 1
    assert public['community']['short'] == []
    assert public['community']['full'] == []

    response = app.test_client().get('/admin/', headers={'Authorization':'Basic YWRtaW46dGVzdC1wYXNzd29yZA=='})
    assert response.status_code == 200
    assert '개발 검증용 데이터이며 실제 실험 집계에는 포함되지 않습니다.' in response.get_data(as_text=True)


def test_fifty_test_visitors_do_not_satisfy_experiment_sample(app):
    from app.services.reporting import test_report as development_report
    app.config['TESTING'] = False
    for _ in range(50):
        person = Participant(app)
        person.action('emoji', option_id='0')
        person.action('short', body='test')
    with app.app_context():
        assert development_report()['scopes']['all']['visitors'] == 50
        data = report()
        assert data['scopes']['all']['visitors'] == 0
        assert not data['sample_met']
        assert data['judgment'] == '판정 불가'
