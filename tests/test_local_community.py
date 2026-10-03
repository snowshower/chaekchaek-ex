from app.db import get_db
from app.services.reporting import report, test_report as development_report
from conftest import Participant, rows


def test_two_local_test_visitors_complete_isolated_community(app):
    real = Participant(app)
    real.action('short', body='real short')
    real.action('observe', event_type='community_open')
    real.action('full', body='real full')
    real.action('emoji', option_id='2')
    real.action('poll', option_id='2')
    real_target = real.state()['own_reviews']['short']['id']
    with app.app_context():
        baseline = report()
    app.config['TESTING'] = False
    a, b = Participant(app), Participant(app)
    assert all(v['is_test'] for v in rows(app, 'visitors', 'visitor_id IN (?,?)', (a.visitor_id(), b.visitor_id())))
    a.action('short', body='A test short')
    a.action('observe', event_type='community_open')
    a.action('full', body='A test full')
    short = a.state()['own_reviews']['short']['id']
    full = a.state()['own_reviews']['full']['id']
    for p in (a, b):
        p.action('emoji', option_id='0')
        p.action('poll', option_id='1')
    b.action('observe', event_type='community_open')
    state = b.state()
    assert [r['id'] for r in state['community']['short']] == [short]
    assert [r['id'] for r in state['community']['full']] == [full]
    assert not state['community']['short'][0]['mine']
    assert a.state()['community']['short'][0]['mine']
    assert a.state()['community']['full'][0]['mine']
    assert state['emoji_results'][0]['count'] == 2
    assert sum(r['count'] for r in state['emoji_results']) == 2
    assert state['poll_results'][1]['count'] == 2
    assert sum(r['count'] for r in state['poll_results']) == 2
    assert not rows(app, 'events', "visitor_id=? AND event_type='others_reveal'", (b.visitor_id(),))
    assert b.post(b.payload('observe', event_type='others_reveal', target_id=short, exposure_area='community_reviews', reveal_source='community_open', visibility_ratio=.49, active_tab=True)).status_code == 400
    b.expose(short)
    b.expose(full)
    b.action('like', target_id=short, active=True)
    b.action('reply', target_id=short, body='B reply')
    card = a.state()['community']['short'][0]
    assert card['likes'] == 1
    assert card['replies'][0]['body'] == 'B reply'
    reply_id = card['replies'][0]['id']
    assert b.state()['community']['short'][0]['replies'][0]['mine']
    with app.app_context():
        actual = report()
        assert actual['scopes'] == baseline['scopes']
        assert actual['sample_met'] == baseline['sample_met']
        assert actual['judgment'] == baseline['judgment']
        test = development_report()['scopes']['all']
        assert test['visitors'] == 2
        assert test['current']['likes'] == test['current']['replies'] == 1
        interaction = next(m for m in test['metrics'] if m['metric_name'] == 'interaction')
        assert (interaction['numerator'], interaction['denominator']) == (1, 1)
    events = rows(app, 'events', 'visitor_id=?', (b.visitor_id(),))
    path = [e['event_type'] for e in sorted(events, key=lambda e: e['client_sequence']) if e['event_type'] in ('community_open', 'others_reveal', 'like', 'reply_submit')]
    assert path == ['community_open', 'others_reveal', 'like', 'reply_submit']
    for viewer, forbidden in ((real, short), (b, real_target)):
        for operation, fields in (('like', {'active': True}), ('reply', {'body': 'cross cohort'})):
            assert viewer.post(viewer.payload(operation, target_id=forbidden, **fields)).status_code == 403
        assert viewer.post(viewer.payload('observe', event_type='others_reveal', target_id=forbidden, exposure_area='community_reviews', reveal_source='community_open', visibility_ratio=.5, active_tab=True)).status_code == 400
    public = real.state()
    assert [r['id'] for r in public['community']['short']] == [real_target]
    assert public['community']['short'][0]['likes'] == 0
    assert public['community']['short'][0]['replies'] == []
    assert sum(r['count'] for r in public['emoji_results']) == 1
    assert sum(r['count'] for r in public['poll_results']) == 1
    b.action('like', target_id=short, active=False)
    b.action('reply', reply_id=reply_id, body='edited')
    assert a.state()['community']['short'][0]['replies'][0]['body'] == 'edited'
    b.action('reply', reply_id=reply_id, delete=True)
    assert a.state()['community']['short'][0]['likes'] == 0
    assert a.state()['community']['short'][0]['replies'] == []
    # The local-only community disappears when the deployment runs in production mode.
    app.config['LOCAL_DEVELOPMENT'] = False
    for viewer in (real, b):
        production = viewer.state()
        assert all(r['id'] == real_target for r in production['community']['short'])
        assert sum(r['count'] for r in production['emoji_results']) == 1
        assert sum(r['count'] for r in production['poll_results']) == 1