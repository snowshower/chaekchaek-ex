"""Capability links for first-entry seed participants; hashes only in storage."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import click
from flask import current_app

from ..db import get_db
from .event_logging import utcnow


def token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def available_invite(token):
    digest = token_hash(token)
    if not digest:
        return None
    return get_db().execute('SELECT token_hash FROM seed_invites WHERE token_hash=? '
                            'AND used_at IS NULL AND expires_at>?', (digest, utcnow())).fetchone()


def create_links(count, base_url, expires_hours):
    # Tokens are returned only after the metadata transaction commits.
    created = utcnow()
    expires = (datetime.fromisoformat(created.replace('Z', '+00:00')) +
               timedelta(hours=expires_hours)).astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    tokens = [secrets.token_urlsafe(32) for _ in range(count)]
    db = get_db()
    db.begin_write()
    try:
        db.execute_batch([('INSERT INTO seed_invites VALUES (?,?,?,NULL)',
                           (token_hash(token), created, expires)) for token in tokens])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return [base_url.rstrip('/') + '/seed/' + token for token in tokens], expires


def validate_origin(base_url, local):
    try:
        parts = urlsplit(base_url)
        if (any(ord(c) <= 32 for c in base_url) or not parts.hostname or
                parts.username is not None or parts.password is not None or
                parts.path not in ('', '/') or parts.query or parts.fragment or
                parts.scheme not in (('http', 'https') if local else ('https',)) or
                not re.fullmatch(r'[A-Za-z0-9.:-]+', parts.hostname)):
            raise ValueError()
        parts.port  # Reject malformed or out-of-range ports before any write.
    except ValueError:
        raise click.UsageError('--base-url must be an origin without credentials, path, query or fragment; production requires HTTPS.') from None
    return base_url.rstrip('/')


def register(app):
    @app.cli.command('create-seed-links')
    @click.option('--count', required=True, type=click.IntRange(1, 100))
    @click.option('--base-url', required=True, help='Public origin, e.g. https://your-production-domain')
    @click.option('--expires-hours', default=72, show_default=True, type=click.IntRange(1, 168))
    @click.option('--confirm-production', is_flag=True, help='Confirm writes to the configured remote/production database.')
    def create_seed_links(count, base_url, expires_hours, confirm_production):
        local = current_app.config['LOCAL_DEVELOPMENT']
        remote = bool(current_app.config.get('DATABASE_URL'))
        production = not local or remote or current_app.config.get('VERCEL', False)
        origin = validate_origin(base_url, local and not production)
        click.echo(f"LOCAL_DEVELOPMENT={int(local)}; database={'PostgreSQL' if remote else 'local SQLite'}; target_origin={origin}")
        if production and not confirm_production:
            raise click.UsageError('Remote/production database writes require --confirm-production. Verify your configured database and target_origin first.')
        try:
            links, expires = create_links(count, origin, expires_hours)
        except Exception:
            raise click.ClickException('Seed link creation failed; no URLs issued. Check schema initialization and database access. Credentials are not displayed.') from None
        click.echo(f'Created {len(links)} single-use links; expires_at={expires} (UTC). Treat URLs as private credentials.')
        for link in links:
            click.echo(link)
