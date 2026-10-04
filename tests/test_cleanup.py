import pytest

from app.db import get_db
from app.services.cleanup import PARTICIPATION_TABLES, PRESERVED_TABLES, cleanup_participation
from app.services.reporting import report
from conftest import Participant


def snapshot(app):
    with app.app_context():
        return {table: [dict(row) for row in get_db().execute(f'SELECT * FROM {table}')]
                for table in PARTICIPATION_TABLES + PRESERVED_TABLES}


@pytest.fixture
def smoke(app):
    a, b = Participant(app), Participant(app)
    a.action('emoji', option_id='0')
    a.action('poll', option_id='1')
    a.action('short', body='smoke short')
    a.action('observe', event_type='community_open')
    a.action('full', body='smoke full')
    target = a.state()['own_reviews']['short']['id']
    b.action('observe', event_type='community_open')
    b.expose(target)
    b.action('like', target_id=target, active=True)
    b.action('reply', target_id=target, body='smoke reply')
    with app.app_context():
        get_db().execute("UPDATE visitors SET is_test=1,exclusion_reason='smoke' WHERE visitor_id=?",
                         (a.visitor_id(),))
    return a, b


def test_cleanup_defaults_to_dry_run_and_counts_all_cohorts(app, smoke):
    before = snapshot(app)
    result = app.test_cli_runner().invoke(args=['cleanup-participation'])
    assert result.exit_code == 0, result.output
    assert 'DRY RUN: no rows deleted' in result.output
    assert 'visitors: 2 (test=1, non_test=1)' in result.output
    for table, rows in before.items():
        assert f'{table}: {len(rows)}' in result.output
    assert snapshot(app) == before


@pytest.mark.parametrize('args', [ ['--execute'], ['--execute', '--confirm-no-real-users'],
    ['--execute', '--expect-visitors', '2'],
    ['--dry-run', '--execute', '--confirm-no-real-users', '--expect-visitors', '2'],
    ['--execute', '--confirm-no-real-users', '--expect-visitors', '3'] ])
def test_cleanup_requires_explicit_confirmation_and_exact_count(app, smoke, args):
    before = snapshot(app)
    result = app.test_cli_runner().invoke(args=['cleanup-participation'] + args)
    assert result.exit_code != 0
    assert snapshot(app) == before


def test_cleanup_preserves_content_and_resets_experiment(app, smoke):
    before = snapshot(app)
    assert all(before[table] for table in PARTICIPATION_TABLES if table != 'seed_participants')
    result = app.test_cli_runner().invoke(args=['cleanup-participation', '--execute',
        '--confirm-no-real-users', '--expect-visitors', '2'])
    assert result.exit_code == 0, result.output
    after = snapshot(app)
    assert all(not after[table] for table in PARTICIPATION_TABLES)
    for table in PRESERVED_TABLES:
        assert after[table] == before[table]
    with app.app_context():
        data = report()
        assert data['scopes']['all']['visitors'] == 0
        assert all(m['numerator'] == 0 for m in data['scopes']['all']['metrics'])
        assert data['judgment'] == '판정 불가'
    # An old cookie recovers as a new visitor after reset.
    smoke[1].open()
    with app.app_context():
        assert report()['scopes']['all']['visitors'] == 1


def test_cleanup_rolls_back_every_delete_on_failure(app, smoke, monkeypatch):
    before = snapshot(app)
    with app.app_context():
        db = get_db()
        execute = db.execute
        def fail(statement, parameters=()):
            if statement == 'DELETE FROM reviews':
                raise RuntimeError('secret credential must not appear')
            return execute(statement, parameters)
        monkeypatch.setattr(db, 'execute', fail)
        with pytest.raises(RuntimeError):
            cleanup_participation(True, 2)
    assert snapshot(app) == before


def test_cleanup_cli_sanitizes_failure(app, monkeypatch):
    import app.services.cleanup as module
    def fail(*args):
        raise RuntimeError('postgresql://secret:password@private/db')
    monkeypatch.setattr(module, 'cleanup_participation', fail)
    result = app.test_cli_runner().invoke(args=['cleanup-participation'])
    assert result.exit_code != 0
    assert 'password' not in result.output and 'postgresql://' not in result.output
