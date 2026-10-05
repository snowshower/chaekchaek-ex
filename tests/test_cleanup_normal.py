import pytest

from app.db import get_db
from app.services.cleanup_normal import cleanup_normal, OWNED_TABLES
from conftest import Participant
from test_cleanup import snapshot
from test_seed import seed_person


@pytest.fixture
def mixed(app):
    seed = seed_person(app)
    normal, test = Participant(app), Participant(app)
    for person in (seed, normal, test):
        person.action('emoji', option_id='0')
        person.action('poll', option_id='1')
        person.action('short', body='short')
        person.action('observe', event_type='community_open')
        person.action('full', body='full')
    target = seed.state()['own_reviews']['short']['id']
    for person in (normal, test):
        person.action('observe', event_type='community_open')
        person.expose(target)
        person.action('like', target_id=target, active=True)
        person.action('reply', target_id=target, body='reply')
    with app.app_context():
        get_db().execute('UPDATE visitors SET is_test=1 WHERE visitor_id=?', (test.visitor_id(),))
    return seed, normal, test


def test_normal_dry_run_and_execute_preserve_every_protected_row(app, mixed):
    before = snapshot(app)
    normal_id = mixed[1].visitor_id()
    result = app.test_cli_runner().invoke(args=['cleanup-normal-participation'])
    assert result.exit_code == 0, result.output
    assert 'DELETE visitors: 1' in result.output
    assert 'PRESERVE seed visitors: 1' in result.output
    assert 'PRESERVE seed reviews: 2' in result.output
    assert 'PRESERVE test visitors: 1' in result.output
    for table in OWNED_TABLES:
        assert f'DELETE {table}: {sum(r["visitor_id"] == normal_id for r in before[table])}' in result.output
    assert snapshot(app) == before
    result = app.test_cli_runner().invoke(args=['cleanup-normal-participation', '--execute',
        '--confirm-no-real-users', '--expect-normal-visitors', '1'])
    assert result.exit_code == 0, result.output
    after = snapshot(app)
    for table, rows in before.items():
        assert after[table] == ([r for r in rows if r['visitor_id'] != normal_id]
                                if table in OWNED_TABLES else rows)
    with app.app_context():
        assert cleanup_normal()[0]['visitors'] == 0


@pytest.mark.parametrize('args', [ ['--execute'],
    ['--execute', '--confirm-no-real-users'],
    ['--execute', '--expect-normal-visitors', '1'],
    ['--execute', '--confirm-no-real-users', '--expect-normal-visitors', '2'],
    ['--dry-run', '--execute', '--confirm-no-real-users', '--expect-normal-visitors', '1'] ])
def test_normal_guards_leave_all_rows_unchanged(app, mixed, args):
    before = snapshot(app)
    result = app.test_cli_runner().invoke(args=['cleanup-normal-participation'] + args)
    assert result.exit_code != 0
    assert snapshot(app) == before


@pytest.mark.parametrize('config', [{'LOCAL_DEVELOPMENT': False},
    {'DATABASE_URL': 'postgresql://secret:password@private/db'}, {'VERCEL': True}])
def test_normal_production_confirmation_before_database_access(app, monkeypatch, config):
    import app.services.cleanup_normal as module
    app.config.update(config)
    monkeypatch.setattr(module, 'cleanup_normal', lambda *args: pytest.fail('must not access DB'))
    result = app.test_cli_runner().invoke(args=['cleanup-normal-participation', '--execute',
        '--confirm-no-real-users', '--expect-normal-visitors', '1'])
    assert result.exit_code != 0
    assert '--confirm-production' in result.output
    assert 'password' not in result.output


def test_normal_failure_rolls_back_all_deletes(app, mixed, monkeypatch):
    before = snapshot(app)
    with app.app_context():
        db = get_db()
        original = db.execute
        def fail(sql, parameters=()):
            if sql.startswith('DELETE FROM reviews'):
                raise RuntimeError('postgresql://secret:password@private/db')
            return original(sql, parameters)
        monkeypatch.setattr(db, 'execute', fail)
        result = app.test_cli_runner().invoke(args=['cleanup-normal-participation', '--execute',
            '--confirm-no-real-users', '--expect-normal-visitors', '1', '--confirm-production'])
        assert result.exit_code != 0
        assert 'rolled back' in result.output
        assert 'password' not in result.output and 'postgresql://' not in result.output
    assert snapshot(app) == before


def test_normal_refuses_protected_actions_on_target_review(app, mixed):
    before = snapshot(app)
    normal_review = mixed[1].state()['own_reviews']['short']['id']
    with app.app_context():
        get_db().execute('UPDATE likes SET review_id=? WHERE visitor_id=?',
                         (normal_review, mixed[2].visitor_id()))
    before = snapshot(app)
    result = app.test_cli_runner().invoke(args=['cleanup-normal-participation', '--execute',
        '--confirm-no-real-users', '--expect-normal-visitors', '1'])
    assert result.exit_code != 0
    assert 'BLOCKING protected likes: 1' in result.output
    assert snapshot(app) == before


def test_normal_count_is_not_hardcoded(app):
    Participant(app)
    Participant(app)
    result = app.test_cli_runner().invoke(args=['cleanup-normal-participation', '--execute',
        '--confirm-no-real-users', '--expect-normal-visitors', '2'])
    assert result.exit_code == 0, result.output
