"""Pre-recruitment reset. No schema changes and no content deletion."""
import click

from ..db import get_db

# Actual schema.sql/schema_postgres.sql dependencies: events -> page_views,
# likes/replies -> reviews, every table below -> visitors. Exposures are events;
# short impressions are reviews; idempotency responses are requests.
PARTICIPATION_TABLES = ('requests', 'events', 'likes', 'replies', 'emoji_reactions',
                        'poll_votes', 'reviews', 'page_views', 'seed_participants', 'visitor_attributions', 'visitors')
PRESERVED_TABLES = ('books', 'book_contents', 'seed_invites')


def cleanup_participation(execute=False, expected_visitors=None):
    db = get_db()
    if execute:
        db.begin_write()
    else:
        db.begin_read()
    try:
        if execute and db.schema_file == 'schema_postgres.sql':
            # Also block writers that do not use the application's advisory lock.
            db.execute('LOCK TABLE ' + ','.join(PARTICIPATION_TABLES) +
                       ' IN SHARE ROW EXCLUSIVE MODE')
        counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in PARTICIPATION_TABLES + PRESERVED_TABLES}
        cohorts = {label: db.execute('SELECT count(*) FROM visitors WHERE is_test=?',
                                    (value,)).fetchone()[0]
                   for label, value in (('test', 1), ('non_test', 0))}
        if execute:
            if expected_visitors is None or counts['visitors'] != expected_visitors:
                raise click.ClickException('Visitor count changed or was not confirmed; run dry-run again.')
            for table in PARTICIPATION_TABLES:
                db.execute(f'DELETE FROM {table}')
            for table in PRESERVED_TABLES:
                if db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] != counts[table]:
                    raise RuntimeError('Preserved content count changed')
            db.commit()
        else:
            db.rollback()
        return counts, cohorts
    except Exception:
        db.rollback()
        raise


def register(app):
    @app.cli.command('cleanup-participation')
    @click.option('--dry-run', is_flag=True, help='Count only (the default).')
    @click.option('--execute', is_flag=True, help='Delete ALL participation, including non-test visitors.')
    @click.option('--confirm-no-real-users', is_flag=True, help='Confirm recruitment has not started.')
    @click.option('--expect-visitors', type=click.IntRange(min=0), help='Exact visitor count from dry-run.')
    def cleanup(dry_run, execute, confirm_no_real_users, expect_visitors):
        if dry_run and execute:
            raise click.UsageError('--dry-run and --execute are mutually exclusive.')
        if execute and (not confirm_no_real_users or expect_visitors is None):
            raise click.UsageError('--execute requires --confirm-no-real-users and --expect-visitors N.')
        try:
            counts, cohorts = cleanup_participation(execute, expect_visitors)
        except click.ClickException:
            raise
        except Exception:
            # Never expose credentials or driver exception text in CLI output.
            raise click.ClickException('Cleanup failed; transaction rolled back. No credentials are displayed.') from None
        click.echo('EXECUTED: participation reset' if execute else 'DRY RUN: no rows deleted')
        click.echo(f"visitors: {counts['visitors']} (test={cohorts['test']}, non_test={cohorts['non_test']})")
        for table in PARTICIPATION_TABLES:
            click.echo(f'{table}: {counts[table]}')
        for table in PRESERVED_TABLES:
            click.echo(f'PRESERVE {table}: {counts[table]}')
