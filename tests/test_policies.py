import io
import json
import zipfile
from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_db
from app.services.reporting import report
from conftest import Participant, rows


def test_cookie_identity_and_no_get_events(app, participant):
    visitor = participant.visitor_id()
    participant.open()
    assert participant.visitor_id() == visitor
    client = app.test_client()
    client.get('/books/metamorphosis', follow_redirects=True)
    assert len(rows(app, 'events', "event_type='book_view'")) == 2
    blocked = app.test_client(use_cookies=False)
    assert blocked.get('/', follow_redirects=True).status_code == 403
    assert len(rows(app, 'events')) == 2
    assert participant.client.get_cookie('visitor_id').http_only
    assert participant.client.get_cookie('visitor_id').same_site == 'Lax'


def test_random_order_persistence_and_select_link(app, participant):
    participant.open(landing=True)
    order = json.loads(rows(app, 'page_views', 'page_view_id=?', (participant.bootstrap['page_view_id'],))[0]['displayed_book_order'])
    event = participant.action('observe', event_type='book_select', book_id=order[1], display_position=2)
    assert participant.post(participant.payload('observe', event_type='book_select', book_id=order[1], display_position=1)).status_code == 400
    response = participant.client.get(f'/books/{order[1]}?selection={event["event_id"]}')
    assert response.status_code == 200
    assert rows(app, 'page_views', 'source_book_select_event_id=?', (event['event_id'],))
    participant.open(landing=True)
    again = rows(app, 'page_views', 'page_view_id=?', (participant.bootstrap['page_view_id'],))[0]
    assert json.loads(again['displayed_book_order']) == order
    assert all(e['book_id'] is None for e in rows(app, 'events', "event_type='landing_view'"))


@pytest.mark.parametrize('kind,event,cancel', [('emoji','emoji_reaction','emoji_cancel'), ('poll','poll_vote','poll_cancel')])
def test_selection_change_cancel_results_and_retry(app, participant, kind, event, cancel):
    assert kind+'_results' not in participant.state()
    payload = participant.payload(kind, option_id='0')
    assert participant.post(payload).status_code == 200
    assert participant.post(payload).status_code == 200
    assert participant.post(dict(payload, option_id='1')).status_code == 409
    participant.action(kind, option_id='0')
    participant.action(kind, option_id='1')
    participant.action(kind, option_id=None)
    participant.action(kind, option_id=None)
    assert len(rows(app,'events','event_type=?',(event,))) == 2
    assert len(rows(app,'events','event_type=?',(cancel,))) == 1
    assert participant.state()[kind+'_selection'] is None
    assert all(r['count'] == 0 and r['ratio'] is None for r in participant.state()[kind+'_results'])
    other = 'poll' if kind == 'emoji' else 'emoji'
    assert other+'_results' not in participant.state()
    assert 'short_reviews' not in participant.state()
    participant.open()
    assert kind+'_results' in participant.state()
    participant.action(kind, option_id='2')
    assert len(rows(app,'events','event_type=?',(event,))) == 3
    participant.open('little-prince')
    assert kind+'_results' not in participant.state()


@pytest.mark.parametrize('kind,limit', [('short',150), ('full',2000)])
def test_review_lifecycle_same_id_and_entitlement(app, participant, kind, limit):
    if kind == 'full': participant.action('observe', event_type='community_open')
    assert participant.post(participant.payload(kind, body='  \n ')).status_code == 400
    assert participant.post(participant.payload(kind, body='😀'*(limit+1))).status_code == 400
    participant.action(kind, body='😀'*limit)
    participant.action(kind, body='수정한 감상')
    participant.action(kind, delete=True)
    before = rows(app,'reviews')[0]
    assert before['deleted_at'] and before['body'] == '수정한 감상'
    assert kind == 'full' or 'short_reviews' in participant.state()
    participant.open()
    assert kind == 'full' or 'short_reviews' in participant.state()
    participant.action(kind, body='다시 쓴 감상')
    after = rows(app,'reviews')[0]
    assert before['review_id'] == after['review_id']
    assert before['first_submitted_at'] == after['first_submitted_at']
    assert not after['deleted_at']
    assert len(rows(app,'events','event_type=?',(kind+'_review_submit',))) == 1
    assert [e['action'] for e in rows(app,'events','event_type=?',(kind+'_review_update',))] == ['edit','restore']
    participant.action('observe',event_type=kind+'_review_start')
    assert not rows(app,'events','event_type=?',(kind+'_review_start',))


def test_community_restore_and_exposure_are_distinct(app, participant):
    writer = Participant(app)
    writer.action('short',body='타인의 한 줄')
    target = writer.state()['own_reviews']['short']['id']
    participant.action('observe',event_type='community_open')
    assert participant.state()['community_open']
    assert 'emoji_results' not in participant.state() and 'poll_results' not in participant.state()
    assert not rows(app,'events',"event_type='others_reveal'")
    participant.expose(target)
    participant.expose(target)
    participant.open()
    assert participant.state()['community_open']
    participant.action('observe',event_type='community_open')
    assert len(rows(app,'events',"event_type='community_open'")) == 1
    participant.expose(target, 'community_restore')
    assert len(rows(app,'events',"event_type='others_reveal'")) == 2
    assert rows(app,'events',"event_type='others_reveal'")[1]['reveal_source'] == 'community_restore'
    participant.action('like',target_id=target,active=True)
    with app.app_context(): assert report()['scopes']['all']['metrics'][6]['ratio'] == 1


def test_individual_short_paths_empty_self_and_threshold(app, participant):
    participant.action('short',body='내 생각')
    mine = participant.state()['own_reviews']['short']['id']
    payload = participant.payload('observe',event_type='others_reveal',target_id=mine,reveal_source='short_review_submit',exposure_area='individual_short_reviews',visibility_ratio=.5,active_tab=True)
    assert participant.post(payload).status_code == 400
    other = Participant(app)
    other.action('short',body='다른 생각')
    target = other.state()['own_reviews']['short']['id']
    below = dict(payload,event_id=str(uuid4()),target_id=target,visibility_ratio=.49)
    assert participant.post(below).status_code == 400
    participant.expose(target,'short_review_submit','individual_short_reviews','short_reviews_reveal')
    participant.expose(target,'short_review_submit','individual_short_reviews')
    participant.action('observe',event_type='community_open')
    participant.expose(target,'community_open','community_reviews','short_reviews_reveal')
    participant.expose(target)
    assert len(rows(app,'events',"event_type='short_reviews_reveal'")) == 2
    assert len(rows(app,'events',"event_type='others_reveal'")) == 1
    participant.open()
    participant.expose(target,'return_visit','individual_short_reviews')


def test_like_reply_security_duplicates_and_cancellation(app, participant):
    writer = Participant(app)
    writer.action('short',body='한 줄')
    writer.action('observe',event_type='community_open')
    writer.action('full',body='자유 감상')
    target = writer.state()['own_reviews']['full']['id']
    assert participant.post(participant.payload('like',target_id=target,active=True)).status_code == 403
    participant.action('observe',event_type='community_open')
    participant.action('like',target_id=target,active=True)
    participant.action('like',target_id=target,active=True)
    participant.action('like',target_id=target,active=False)
    participant.action('like',target_id=target,active=False)
    participant.action('like',target_id=target,active=True)
    assert len(rows(app,'likes')) == 1
    assert len(rows(app,'events',"event_type='like'")) == 2
    assert len(rows(app,'events',"event_type='like_cancel'")) == 1
    payload = participant.payload('reply',target_id=target,body='답글')
    participant.post(payload); participant.post(payload)
    participant.action('reply',target_id=target,body='답글')
    replies = rows(app,'replies')
    assert len(replies) == 2  # Intentional same-body new replies are distinct.
    participant.action('reply',reply_id=replies[0]['reply_id'],body='수정')
    participant.action('reply',reply_id=replies[0]['reply_id'],delete=True)
    assert len(rows(app,'events',"event_type='reply_submit'")) == 2
    assert len(participant.state()['community']['full'][0]['replies']) == 1
    assert writer.post(writer.payload('reply',reply_id=replies[1]['reply_id'],body='가로채기')).status_code == 403
    assert writer.post(writer.payload('like',target_id=target,active=True)).status_code == 403
    participant.open('little-prince'); participant.action('observe',event_type='community_open')
    assert participant.post(participant.payload('like',target_id=target,active=True)).status_code == 403
    writer.action('full',delete=True)
    participant.open()
    assert participant.post(participant.payload('reply',target_id=target,body='삭제된 글')).status_code == 403


def test_test_visitors_public_and_metrics_excluded(app, participant):
    participant.action('emoji',option_id='0')
    participant.action('short',body='테스트 글')
    runner = app.test_cli_runner()
    assert runner.invoke(args=['mark-test', participant.visitor_id(), '--reason','development']).exit_code == 0
    actual = Participant(app)
    actual.action('emoji',option_id='1')
    actual.action('observe',event_type='community_open')
    assert sum(r['count'] for r in actual.state()['emoji_results']) == 1
    assert actual.state()['community']['short'] == []
    with app.app_context():
        result = report()
        assert result['scopes']['all']['visitors'] == 1
        assert result['quality']['excluded_events'] == 3


def test_admin_auth_export_and_secret_exclusion(app, participant):
    participant.action('short',body='=HYPERLINK("a,b")\n😀')
    assert participant.client.get('/admin').status_code == 401
    assert participant.client.get('/admin/export').status_code == 401
    auth = {'Authorization':'Basic YWRtaW46dGVzdC1wYXNzd29yZA=='}
    response = participant.client.get('/admin',headers=auth)
    assert response.status_code == 200
    assert rows(app,'visitors')[0]['is_test'] == 0
    assert participant.client.get_cookie('admin_test') is None
    download = participant.client.get('/admin/export',headers=auth)
    archive = zipfile.ZipFile(io.BytesIO(download.data))
    assert 'metrics.csv' in archive.namelist()
    assert 'is_test' in archive.read('events.csv').decode('utf-8-sig')
    assert 'csrf_token' not in archive.read('visitors.csv').decode('utf-8-sig')
    assert "'=HYPERLINK" in archive.read('reviews.csv').decode('utf-8-sig')
    assert '😀' in archive.read('reviews.csv').decode('utf-8-sig')
    app.config['ADMIN_PASSWORD'] = None
    assert participant.client.get('/admin',headers=auth).status_code == 503


def test_csrf_and_failed_save_rollback(app,participant):
    p = participant.payload('short',body='반드시 원자적 저장')
    assert participant.client.post('/api/actions',json=p).status_code == 403
    # Force event failure after review row insertion; transaction must roll back both.
    p['client_sequence'] = 1
    assert participant.post(p).status_code == 409
    assert not rows(app,'reviews')
    assert len(rows(app,'events')) == 1


def test_body_purge_preserves_history(app,participant):
    participant.action('short',body='삭제 본문')
    participant.action('short',delete=True)
    app.config['EXPERIMENT_START'] = '2020-01-01T00:00:00.000000Z'
    app.config['EXPERIMENT_END'] = '2026-01-01T00:00:00.000000Z'
    runner = app.test_cli_runner()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace('+00:00', 'Z')
    assert runner.invoke(args=['purge-deleted-bodies','--before',future,'--confirm-copy-policy']).exit_code != 0
    # Use a past cutoff after this test's deletion through an explicit controlled timestamp.
    with app.app_context(): get_db().execute("UPDATE reviews SET deleted_at='2025-01-01T00:00:00.000000Z'")
    result = runner.invoke(args=['purge-deleted-bodies','--before','2026-01-01T00:00:00Z','--confirm-copy-policy'])
    assert result.exit_code == 0, result.output
    review = rows(app,'reviews')[0]
    assert review['body'] == '' and review['body_purged_at']
    assert len(rows(app,'events',"event_type='short_review_submit'")) == 1


def test_cards_multiple_valid_others_and_invalid_targets(app, participant):
    writers = [Participant(app) for _ in range(2)]
    targets = []
    for writer in writers:
        writer.action('short', body='valid other card')
        targets.append(writer.state()['own_reviews']['short']['id'])
    participant.action('observe', event_type='community_open')
    for target in targets:
        participant.expose(target)
    assert len(rows(app, 'events', "event_type='others_reveal'")) == 1
    with app.app_context():
        data = report()
        exposure = next(m for m in data['scopes']['all']['metrics'] if m['metric_name'] == 'others_exposure')
        assert exposure['numerator'] == 1
        assert exposure['denominator'] == 3
    assert participant.post(participant.payload('observe', event_type='others_reveal', target_id=targets[0], reveal_source='community_open', exposure_area='community_reviews', visibility_ratio=.5, active_tab=False)).status_code == 400
    writers[0].action('short', delete=True)
    assert participant.post(participant.payload('observe', event_type='others_reveal', target_id=targets[0], reveal_source='community_open', exposure_area='community_reviews', visibility_ratio=1, active_tab=True)).status_code == 400
