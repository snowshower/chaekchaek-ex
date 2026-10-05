"""Selective pre-recruitment cleanup; seed and test actors are protected."""
import click
from flask import current_app

from ..cohorts import non_seed
from ..db import get_db
from .cleanup import PARTICIPATION_TABLES, PRESERVED_TABLES

OWNED_TABLES = tuple(t for t in PARTICIPATION_TABLES if t != 'seed_participants')
TARGETS = 'SELECT v.visitor_id FROM visitors v WHERE v.is_test=0 AND ' + non_seed('v')


def cleanup_normal(execute=False, expected_visitors=None, announce=None):
    db = get_db()
    try:
        if execute:
            db.begin_write()
            if db.schema_file == 'schema_postgres.sql':
                db.execute('LOCK TABLE ' + ','.join(PARTICIPATION_TABLES + PRESERVED_TABLES) +
                           ' IN SHARE ROW EXCLUSIVE MODE')
        else:
            db.begin_read()
        counts = {t: db.execute(f'SELECT count(*) FROM {t} WHERE visitor_id IN ({TARGETS})').fetchone()[0]
                  for t in OWNED_TABLES}
        preserved = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                     for t in ('seed_participants',) + PRESERVED_TABLES}
        preserved['seed visitors'] = db.execute('SELECT count(*) FROM visitors WHERE visitor_id IN (SELECT visitor_id FROM seed_participants)').fetchone()[0]
        preserved['seed reviews'] = db.execute('SELECT count(*) FROM reviews WHERE visitor_id IN (SELECT visitor_id FROM seed_participants)').fetchone()[0]
        preserved['test visitors'] = db.execute('SELECT count(*) FROM visitors WHERE is_test=1').fetchone()[0]
        # Cross-owner FK references cannot be removed without deleting protected actions.
        blockers = {t: db.execute(f'SELECT count(*) FROM {t} WHERE visitor_id NOT IN ({TARGETS}) AND {column} IN ({references})').fetchone()[0]
                    for t, column, references in (
                        ('likes', 'review_id', f'SELECT review_id FROM reviews WHERE visitor_id IN ({TARGETS})'),
                        ('replies', 'review_id', f'SELECT review_id FROM reviews WHERE visitor_id IN ({TARGETS})'),
                        ('events', 'page_view_id', f'SELECT page_view_id FROM page_views WHERE visitor_id IN ({TARGETS})'))}
        if announce:
            announce(counts, preserved, blockers)
        if execute:
            if expected_visitors is None or counts['visitors'] != expected_visitors:
                raise click.ClickException('Normal visitor count changed or was not confirmed; run dry-run again.')
            if any(blockers.values()):
                raise click.ClickException('Protected actors reference target rows; cleanup refused and rolled back.')
            # Visitors are deleted last, keeping this target subquery stable throughout.
            for table in OWNED_TABLES:
                db.execute(f'DELETE FROM {table} WHERE visitor_id IN ({TARGETS})')
            db.commit()
        else:
            db.rollback()
        return counts, preserved, blockers
    except Exception:
        db.rollback()
        raise


def register(app):
    @app.cli.command('cleanup-normal-participation')
    @click.option('--dry-run', is_flag=True, help='Count only (the default).')
    @click.option('--execute', is_flag=True)
    @click.option('--expect-normal-visitors', type=click.IntRange(min=0))
    @click.option('--confirm-no-real-users', is_flag=True)
    @click.option('--confirm-production', is_flag=True)
    def cleanup(dry_run, execute, expect_normal_visitors, confirm_no_real_users, confirm_production):
        if dry_run and execute:
            raise click.UsageError('--dry-run and --execute are mutually exclusive.')
        if execute and (not confirm_no_real_users or expect_normal_visitors is None):
            raise click.UsageError('--execute requires --confirm-no-real-users and --expect-normal-visitors N.')
        production = (not current_app.config['LOCAL_DEVELOPMENT'] or
                      bool(current_app.config.get('DATABASE_URL')) or current_app.config.get('VERCEL', False))
        if execute and production and not confirm_production:
            raise click.UsageError('Production/remote cleanup requires --confirm-production.')

        def announce(counts, preserved, blockers):
            click.echo('PLAN: non-seed normal actors only')
            for table, count in counts.items():
                click.echo(f'DELETE {table}: {count}')
            for table, count in preserved.items():
                click.echo(f'PRESERVE {table}: {count}')
            for table, count in blockers.items():
                click.echo(f'BLOCKING protected {table}: {count}')
        try:
            cleanup_normal(execute, expect_normal_visitors, announce)
        except click.ClickException:
            raise
        except Exception:
            raise click.ClickException('Cleanup failed; transaction rolled back. Credentials are not displayed.') from None
        click.echo('EXECUTED: normal participation cleaned' if execute else 'DRY RUN: no rows deleted')
