import csv
import io
import json
import re
import secrets
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from threading import Barrier
from urllib.parse import urlsplit

import pytest

from app.db import get_db, init_db
from app.report_queries import period_events
from app.services.cleanup import cleanup_participation
from app.services.reporting import export_zip, report
from app.services.seed import token_hash
from conftest import Participant, rows


def issue_links(app, count=1):
    result = app.test_cli_runner().invoke(args=['create-seed-links', '--count', str(count),
        '--base-url', 'https://localhost', '--confirm-production'])
    assert result.exit_code == 0, result.output
    return [line for line in result.output.splitlines() if line.startswith('https://')]


def invite_form(client, link):
    response = client.get(urlsplit(link).path, base_url='https://localhost')
    if response.status_code != 200:
        return response, None
    html = response.get_data(as_text=True)
    return response, {name: unescape(re.search(f'name="{name}" value="([^"]+)"', html).group(1))
                      for name in ('token', 'proof')}


def accept(client, form, follow=False):
    return client.post('/seed/activate', data=form, base_url='https://localhost', follow_redirects=follow)


def seed_person(app):
    client = app.test_client()
    _, form = invite_form(client, issue_links(app)[0])
    assert accept(client, form, True).status_code == 200
    person = Participant.__new__(Participant)
    person.app, person.client, person.sequence = app, client, 0
    person.open()
    return person


def test_link_generation_stores_only_hashes_and_creates_no_participation(app):
    result = issue_links(app, 5)
    assert len(result) == len(set(result)) == 5
    tokens = [urlsplit(link).path.split('/')[-1] for link in result]
    invites = rows(app, 'seed_invites')
    assert {row['token_hash'] for row in invites} == {token_hash(t) for t in tokens}
    assert all(row['used_at'] is None and row['expires_at'] > row['created_at'] for row in invites)
    assert all(token not in json.dumps(invites) for token in tokens)
    for table in ('visitors', 'seed_participants', 'events', 'page_views', 'requests'):
        assert rows(app, table) == []
    with app.app_context():
        assert report()['scopes']['all']['visitors'] == 0


@pytest.mark.parametrize('count', ['0', '-1', '101', '1.5'])
def test_link_count_bounds_reject_before_writing(app, count):
    result = app.test_cli_runner().invoke(args=['create-seed-links', '--count', count,
                                               '--base-url', 'https://localhost'])
    assert result.exit_code != 0
    assert rows(app, 'seed_invites') == []


@pytest.mark.parametrize('base', ['https://user:password@example.com', 'https://example.com/path',
    'https://example.com?secret=value', 'https://example.com#fragment',
    'https://example.com:99999', 'https://example.com\n', 'file:///private'])
def test_invalid_origins_do_not_write_or_echo_sensitive_input(app, base):
    result = app.test_cli_runner().invoke(args=['create-seed-links', '--count', '1', '--base-url', base])
    assert result.exit_code != 0
    assert 'password' not in result.output and 'secret=value' not in result.output
    assert rows(app, 'seed_invites') == []


@pytest.mark.parametrize('local', [False, True])
def test_production_link_generation_requires_explicit_confirmation(app, monkeypatch, local):
    # Do not connect to a remote database: guard must refuse before any DB access.
    import app.services.seed as module
    app.config.update(LOCAL_DEVELOPMENT=local, DATABASE_URL='postgresql://hidden:credential@private/db')
    monkeypatch.setattr(module, 'create_links', lambda *args: pytest.fail('must not generate without confirmation'))
    result = app.test_cli_runner().invoke(args=['create-seed-links', '--count', '5', '--base-url', 'https://production.example'])
    assert result.exit_code != 0
    assert f'LOCAL_DEVELOPMENT={int(local)}' in result.output and 'database=PostgreSQL' in result.output
    assert '--confirm-production' in result.output
    assert 'credential' not in result.output and 'postgresql://' not in result.output


def test_cli_failures_never_print_credentials_or_tokens(app, monkeypatch):
    import app.services.seed as module
    def fail(*args):
        raise RuntimeError('postgresql://secret:password@private/db')
    monkeypatch.setattr(module, 'create_links', fail)
    result = app.test_cli_runner().invoke(args=['create-seed-links', '--count', '1',
        '--base-url', 'https://localhost', '--confirm-production'])
    assert result.exit_code != 0
    assert 'password' not in result.output and 'postgresql://' not in result.output
    assert not any(line.startswith('https://') for line in result.output.splitlines())


def test_first_entry_consumes_once_and_seed_survives_revisit(app):
    link = issue_links(app)[0]
    client = app.test_client()
    for _ in range(2):
        response, form = invite_form(client, link)
        assert response.status_code == 200
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        assert response.headers['Cache-Control'] == 'no-store'
        assert rows(app, 'visitors') == [] and rows(app, 'seed_invites')[0]['used_at'] is None
    nonce = client.get_cookie('seed_onboarding', path='/seed').value
    assert accept(client, form, True).status_code == 200
    visitor = rows(app, 'visitors')[0]
    assert visitor['is_test'] == 0 and visitor['exclusion_reason'] is None
    assert rows(app, 'seed_participants')[0]['visitor_id'] == visitor['visitor_id']
    assert rows(app, 'seed_invites')[0]['used_at'] is not None
    assert rows(app, 'events') == []
    assert client.get('/books/metamorphosis', follow_redirects=True).status_code == 200
    assert len(rows(app, 'visitors')) == 1
    assert rows(app, 'seed_participants')[0]['visitor_id'] == visitor['visitor_id']
    other = app.test_client()
    assert invite_form(other, link)[0].status_code == 400
    # Possession of the original valid proof is also insufficient after consumption.
    other.set_cookie('seed_onboarding', nonce, path='/seed')
    assert accept(other, form).status_code == 400
    assert len(rows(app, 'visitors')) == 1


@pytest.mark.parametrize('kind', ['malformed', 'unknown', 'expired'])
def test_invalid_or_expired_link_never_creates_a_visitor(app, kind):
    token = 'invalid' if kind == 'malformed' else secrets.token_urlsafe(32)
    if kind == 'expired':
        link = issue_links(app)[0]
        token = urlsplit(link).path.split('/')[-1]
        with app.app_context():
            get_db().execute("UPDATE seed_invites SET expires_at='2000-01-01T00:00:00.000000Z'")
    response = app.test_client().get('/seed/' + token)
    assert response.status_code == 400
    assert rows(app, 'visitors') == [] and rows(app, 'seed_participants') == []


def test_expiry_between_opening_and_accepting_is_checked_atomically(app):
    client = app.test_client()
    _, form = invite_form(client, issue_links(app)[0])
    with app.app_context():
        get_db().execute("UPDATE seed_invites SET expires_at='2000-01-01T00:00:00.000000Z'")
    assert accept(client, form).status_code == 400
    assert rows(app, 'visitors') == [] and rows(app, 'seed_invites')[0]['used_at'] is None


def test_normal_visitor_is_never_converted_even_after_form_was_opened(app):
    link = issue_links(app)[0]
    client = app.test_client()
    _, form = invite_form(client, link)
    assert client.get('/', follow_redirects=True).status_code == 200
    visitor = rows(app, 'visitors')[0]
    assert rows(app, 'seed_participants') == []
    assert invite_form(client, link)[0].status_code == 409
    assert accept(client, form).status_code == 409
    assert rows(app, 'visitors')[0] == visitor
    assert rows(app, 'seed_invites')[0]['used_at'] is None


def test_invalid_existing_visitor_cookie_is_also_rejected(app):
    client = app.test_client()
    client.set_cookie('visitor_id', 'invalid-stale-cookie')
    assert invite_form(client, issue_links(app)[0])[0].status_code == 409
    assert rows(app, 'visitors') == []


def test_activation_requires_browser_bound_signed_form(app):
    link = issue_links(app)[0]
    client = app.test_client()
    _, form = invite_form(client, link)
    assert accept(app.test_client(), form).status_code == 403
    assert accept(client, dict(form, proof='forged')).status_code == 403
    assert accept(client, dict(form, token=secrets.token_urlsafe(32))).status_code == 403
    assert client.post('/seed/activate', data=form, base_url='https://localhost',
                       headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    assert client.post('/seed/activate', data=dict(form, proof='forged'), base_url='https://localhost',
                       headers={'Origin': 'null'}).status_code == 403
    assert rows(app, 'visitors') == [] and rows(app, 'seed_invites')[0]['used_at'] is None
    assert client.post('/seed/activate', data=form, base_url='https://localhost',
                       headers={'Origin': 'null'}).status_code == 303


def test_concurrent_redemptions_create_exactly_one_seed_visitor(app):
    link = issue_links(app)[0]
    clients = [app.test_client(), app.test_client()]
    forms = [invite_form(c, link)[1] for c in clients]
    barrier = Barrier(2)
    def redeem(i):
        barrier.wait(timeout=10)
        return accept(clients[i], forms[i]).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(redeem, range(2)))
    assert sorted(statuses) == [303, 400]
    assert len(rows(app, 'visitors')) == len(rows(app, 'seed_participants')) == 1


def test_visitor_creation_failure_rolls_back_token_consumption(app, monkeypatch):
    from app.db_backend import SQLite, PostgreSQL
    backend = PostgreSQL if app.config['DATABASE_URL'] else SQLite
    original = backend.execute
    def fail(db, statement, parameters=()):
        if statement.startswith('INSERT INTO seed_participants'):
            raise RuntimeError('injected failure')
        return original(db, statement, parameters)
    client = app.test_client()
    _, form = invite_form(client, issue_links(app)[0])
    with monkeypatch.context() as m:
        m.setattr(backend, 'execute', fail)
        with pytest.raises(RuntimeError, match='injected failure'):
            accept(client, form)
    assert rows(app, 'visitors') == [] and rows(app, 'seed_participants') == []
    assert rows(app, 'seed_invites')[0]['used_at'] is None
    assert accept(client, form).status_code == 303


def test_production_requires_https_and_uses_secure_seed_cookie(app):
    link = issue_links(app)[0]
    app.config['LOCAL_DEVELOPMENT'] = False
    client = app.test_client()
    assert client.get(urlsplit(link).path).status_code == 403
    response, form = invite_form(client, link)
    assert response.status_code == 200
    assert client.get_cookie('seed_onboarding', path='/seed').secure
    assert accept(client, form, True).status_code == 200
    assert client.get_cookie('visitor_id').secure
    assert len(rows(app, 'seed_participants')) == 1


def test_seed_reviews_public_but_seed_actions_excluded_and_normal_interactions_count(app):
    seed = seed_person(app)
    seed.action('emoji', option_id='0')
    seed.action('poll', option_id='0')
    seed.action('short', body='seed short body')
    seed.action('observe', event_type='community_open')
    seed.action('full', body='seed full body')
    short = seed.state()['own_reviews']['short']['id']
    full = seed.state()['own_reviews']['full']['id']
    seed_id = seed.visitor_id()
    seed.open(landing=True)
    seed.action('observe', event_type='book_select', book_id='metamorphosis',
                display_position=json.loads(rows(app, 'page_views', 'page_view_id=?',
                (seed.bootstrap['page_view_id'],))[0]['displayed_book_order']).index('metamorphosis') + 1)
    seed.open()
    with app.app_context():
        data = report()
        assert data['scopes']['all']['visitors'] == 0
        assert all(m['numerator'] == 0 for m in data['scopes']['all']['metrics'])
        assert all(e['count'] == 0 for e in data['scopes']['all']['events'])
        assert data['landing']['count'] == data['selection']['count'] == 0
        assert period_events(True) == []
    normal = Participant(app)
    normal.action('emoji', option_id='1')
    normal.action('poll', option_id='1')
    normal.action('short', body='normal short body')
    normal_short = normal.state()['own_reviews']['short']['id']
    normal.action('observe', event_type='community_open')
    public = normal.state()
    assert short in [r['id'] for r in public['short_reviews']]
    assert short in [r['id'] for r in public['community']['short']]
    assert full in [r['id'] for r in public['community']['full']]
    assert public['emoji_results'][0]['count'] == public['poll_results'][0]['count'] == 0
    assert sum(r['count'] for r in public['emoji_results']) == 1
    assert sum(r['count'] for r in public['poll_results']) == 1
    # Production public content is the same, including seed short/full.
    app.config['LOCAL_DEVELOPMENT'] = False
    assert short in [r['id'] for r in normal.state()['community']['short']]
    assert full in [r['id'] for r in normal.state()['community']['full']]
    app.config['LOCAL_DEVELOPMENT'] = True
    normal.expose(short)
    normal.expose(full)
    normal.action('like', target_id=short, active=True)
    normal.action('reply', target_id=short, body='normal reply on seed')
    seed.action('observe', event_type='community_open')
    seed.expose(normal_short, 'community_restore')
    seed.action('like', target_id=normal_short, active=True)
    seed.action('reply', target_id=normal_short, body='seed reply body')
    with app.app_context():
        data = report()
        total = data['scopes']['all']
        assert total['visitors'] == 1
        metrics = {m['metric_name']: m for m in total['metrics']}
        for name in ('light_participation', 'text_participation', 'community_direct',
                     'others_exposure', 'like_after_exposure', 'reply_after_exposure', 'interaction'):
            assert metrics[name]['numerator'] == metrics[name]['denominator'] == 1
        assert metrics['full_participation']['numerator'] == 0
        events = {e['name']: e for e in total['events']}
        assert events['others_reveal']['count'] == 1  # Original per-page dedup definition.
        assert events['like']['count'] == events['reply_submit']['count'] == 1
        assert all(e['visitor_id'] != seed_id for e in period_events(True))
        assert total['current']['likes'] == total['current']['replies'] == 1
        assert total['current']['short_reviews'] == 1 and total['current']['full_reviews'] == 0
        archive = zipfile.ZipFile(io.BytesIO(export_zip()))
    for name in ('visitors.csv', 'events.csv', 'reviews.csv', 'page_views.csv',
                 'emoji_reactions.csv', 'poll_votes.csv', 'likes.csv', 'replies.csv'):
        text = archive.read(name).decode('utf-8-sig')
        records = list(csv.DictReader(io.StringIO(text)))
        assert all(row['visitor_id'].removeprefix("'") != seed_id for row in records)
        assert 'seed short body' not in text and 'seed full body' not in text and 'seed reply body' not in text
    assert 'normal reply on seed' in archive.read('replies.csv').decode('utf-8-sig')
    assert short in archive.read('events.csv').decode('utf-8-sig')
    assert 'seed_invites.csv' not in archive.namelist()


def test_seed_links_and_designations_survive_repeated_init_and_cleanup_keeps_used_invites(app):
    seed = seed_person(app)
    seed.action('short', body='seed short')
    before_contents = rows(app, 'book_contents')
    before_invites = rows(app, 'seed_invites')
    with app.app_context():
        init_db()
        init_db()
        assert rows(app, 'seed_invites') == before_invites
        assert len(rows(app, 'seed_participants')) == 1
        cleanup_participation(True, 1)
    assert rows(app, 'visitors') == [] and rows(app, 'seed_participants') == []
    assert rows(app, 'seed_invites') == before_invites
    assert rows(app, 'book_contents') == before_contents


def test_additive_schema_init_migrates_legacy_database_without_reclassifying_history(app):
    normal = Participant(app)
    normal.action('short', body='existing history')
    before = {table: rows(app, table) for table in ('visitors', 'events', 'reviews', 'book_contents')}
    with app.app_context():
        db = get_db()
        db.execute('DROP TABLE seed_participants')
        db.execute('DROP TABLE seed_invites')
        init_db()
        init_db()
    for table, records in before.items():
        assert rows(app, table) == records
    assert rows(app, 'seed_participants') == rows(app, 'seed_invites') == []
    with app.app_context():
        assert report()['scopes']['all']['visitors'] == 1
