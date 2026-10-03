import json
import sqlite3
from pathlib import Path

import click
from flask import current_app, g

from .config import ROOT


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=5, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA busy_timeout=5000")
    return g.db


def init_db():
    db = get_db()
    db.executescript((ROOT / "app/schema.sql").read_text(encoding="utf-8"))
    db.execute("PRAGMA journal_mode=WAL")
    for book in json.loads((ROOT / "data/books.json").read_text(encoding="utf-8")):
        db.execute("INSERT OR IGNORE INTO books VALUES (?,?)", (book["id"], book["title"]))
        encoded = json.dumps(book, ensure_ascii=False, sort_keys=True)
        existing = db.execute("SELECT content_json FROM book_contents WHERE content_version_id=?", (book["version"],)).fetchone()
        if existing and existing[0] != encoded:
            raise RuntimeError("콘텐츠 변경 시 새로운 version과 effective_at을 지정하세요.")
        db.execute("INSERT OR IGNORE INTO book_contents VALUES (?,?,?,?)", (book["version"], book["id"], encoded, book["effective_at"]))


def register(app):
    @app.teardown_appcontext
    def close(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.cli.command("init-db")
    def initialize():
        init_db()
        click.echo("DB와 콘텐츠 버전 등록 완료")

    @app.cli.command("mark-test")
    @click.argument("visitor_id")
    @click.option("--reason", required=True)
    def mark_test(visitor_id, reason):
        result = get_db().execute("UPDATE visitors SET is_test=1, exclusion_reason=? WHERE visitor_id=?", (reason, visitor_id))
        if not result.rowcount:
            raise click.ClickException("발급된 visitor ID가 아닙니다.")
        click.echo("전체 이력을 테스트 데이터로 제외했습니다.")

    @app.cli.command("purge-deleted-bodies")
    @click.option("--before", required=True, help="운영자가 정한 UTC 폐기 기준 시각")
    @click.option("--confirm-copy-policy", is_flag=True, required=True)
    def purge(before, confirm_copy_policy):
        from .services.event_logging import utcnow, validate_utc
        end = current_app.config["EXPERIMENT_END"]
        if not end or validate_utc(end) > utcnow():
            raise click.ClickException("확정 종료 이후에만 폐기할 수 있습니다.")
        cutoff = validate_utc(before)
        if cutoff > utcnow():
            raise click.ClickException("미래 기준으로 폐기할 수 없습니다.")
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            for table in ("reviews", "replies"):
                db.execute(f"UPDATE {table} SET body='',body_purged_at=? WHERE deleted_at IS NOT NULL AND deleted_at<? AND body_purged_at IS NULL", (utcnow(), cutoff))
            db.commit()
        except Exception:
            db.rollback()
            raise
        click.echo("삭제 상태 본문 폐기 완료. 기존 Export와 백업 사본에도 확정한 정책을 적용하세요.")
