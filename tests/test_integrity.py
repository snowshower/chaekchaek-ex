from concurrent.futures import ThreadPoolExecutor

from app.db import get_db
from conftest import Participant, rows


def test_concurrent_retry_and_distinct_tab_submissions(app,participant):
    token = participant.client.get_cookie('visitor_id').value
    payload = participant.payload('short',body='동시 제출')
    def send(body):
        client = app.test_client()
        client.set_cookie('visitor_id',token)
        return client.post('/api/actions',json=body,headers={'X-CSRF-Token':participant.bootstrap['csrf']}).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(send,[payload]*4)) == [200]*4
    assert len(rows(app,'reviews')) == 1
    assert len(rows(app,'events',"event_type='short_review_submit'")) == 1
    second = participant.payload('short',body='동시 제출')
    assert send(second) == 200
    assert len(rows(app,'events',"event_type='short_review_submit'")) == 1


def test_results_exposure_start_rules_and_test_public_interactions(app,participant):
    assert participant.post(participant.payload('observe',event_type='emoji_results_reveal',visibility_ratio=.5,active_tab=True)).status_code == 403
    participant.action('emoji',option_id='0')
    for _ in range(2): participant.action('observe',event_type='emoji_results_reveal',visibility_ratio=.5,active_tab=True)
    assert len(rows(app,'events',"event_type='emoji_results_reveal'")) == 1
    assert participant.post(participant.payload('observe',event_type='poll_results_reveal',visibility_ratio='0.8',active_tab=True)).status_code == 400
    for _ in range(2): participant.action('observe',event_type='short_review_start')
    assert len(rows(app,'events',"event_type='short_review_start'")) == 1
    writer = Participant(app)
    writer.action('short',body='원글')
    target = writer.state()['own_reviews']['short']['id']
    participant.action('observe',event_type='community_open')
    participant.action('like',target_id=target,active=True)
    for _ in range(2): participant.action('observe',event_type='reply_start',target_id=target)
    assert len(rows(app,'events',"event_type='reply_start'")) == 1
    assert participant.post(participant.payload('reply',target_id=target,body='😀'*301)).status_code == 400
    participant.action('reply',target_id=target,body='테스트 답글')
    app.test_cli_runner().invoke(args=['mark-test',participant.visitor_id(),'--reason','developer'])
    viewer = Participant(app)
    viewer.action('observe',event_type='community_open')
    review = viewer.state()['community']['short'][0]
    assert review['likes'] == 0 and review['replies'] == []


def test_admin_browser_remains_real_and_https_required(app):
    client = app.test_client()
    auth={'Authorization':'Basic YWRtaW46dGVzdC1wYXNzd29yZA=='}
    assert client.get('/admin/',headers=auth).status_code == 200
    assert client.get('/books/metamorphosis',follow_redirects=True).status_code == 200
    assert rows(app,'visitors')[0]['is_test'] == 0
    assert client.get_cookie('admin_test') is None
    app.config['LOCAL_DEVELOPMENT'] = False
    assert client.get('/admin/',headers=auth).status_code == 403
    assert client.get('/admin/',headers=auth,base_url='https://localhost').status_code == 200


def test_cards_exposure_and_end_reject_new_collection(app,participant):
    assert participant.post(participant.payload('observe',event_type='excerpt_view',visibility_ratio=.5,active_tab=True)).status_code == 200
    app.config['EXPERIMENT_END'] = '2020-01-01T00:00:00.000000Z'
    assert participant.post(participant.payload('emoji',option_id='0')).status_code == 403
    assert not rows(app,'emoji_reactions')


def test_html_user_content_is_not_interpreted_and_reply_delete_hidden(app,participant):
    writer=Participant(app)
    writer.action('short',body='<script>alert(1)</script>')
    target=writer.state()['own_reviews']['short']['id']
    participant.action('observe',event_type='community_open')
    participant.action('reply',target_id=target,body='<b>답글</b>')
    reply_id=rows(app,'replies')[0]['reply_id']
    participant.action('reply',reply_id=reply_id,delete=True)
    assert participant.state()['community']['short'][0]['body']=='<script>alert(1)</script>'
    assert participant.state()['community']['short'][0]['replies']==[]
    # Public HTML never interpolates user bodies; JS builds textContent nodes.
    response=participant.client.get('/books/metamorphosis')
    assert '<script>alert(1)</script>' not in response.get_data(as_text=True)


def test_response_state_uses_original_success_page_for_multitab_reveal(app,participant):
    first_page=participant.bootstrap['page_view_id']
    participant.action('short',body='첫 제출')
    participant.open()
    result=participant.action('short',body='다른 탭에서 수정')
    assert result['state']['origins']['short']==first_page
    assert result['state']['origins']['short']!=participant.bootstrap['page_view_id']
    assert result['state']['entitlements']['short']
    assert 'emoji_results' not in result['state']


def test_legacy_pending_startup_uses_confirmed_cards(tmp_path):
    from app import create_app
    from app.db import init_db
    legacy = create_app({'DATABASE': str(tmp_path / 'legacy.sqlite'), 'SECRET_KEY': 'legacy-secret',
                         'LOCAL_DEVELOPMENT': True, 'EXPOSURE_POLICY': 'pending'})
    assert legacy.config['EXPOSURE_POLICY'] == 'cards'
    with legacy.app_context():
        init_db()
    a, b = Participant(legacy), Participant(legacy)
    assert b.bootstrap['exposure_policy'] == 'cards'
    a.action('short', body='legacy configuration test')
    b.action('observe', event_type='community_open')
    b.expose(a.state()['own_reviews']['short']['id'])
    assert len(rows(legacy, 'events', "event_type='others_reveal'")) == 1
