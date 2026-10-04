import json
from time import perf_counter

import click
from flask import current_app, g

from .config import ROOT
from .db_backend import connect, IntegrityError, OperationalError, validate_configuration


def get_db():
    if "db" not in g:
        observer = current_app.config.get("DATABASE_PROFILE_OBSERVER")
        started = perf_counter()
        db = connect(current_app.config)
        if observer:
            from .db_profiling import ProfiledDB
            observer("db.acquire", perf_counter() - started, 1)
            db = ProfiledDB(db, observer)
        g.db = db
    return g.db


def init_db():
    db = get_db()
    db.initialize_schema((ROOT / "app" / db.schema_file).read_text(encoding="utf-8"))
    db.begin_write()
    try:
        contents = json.loads((ROOT / "data/books.json").read_text(encoding="utf-8"))
        cursors = db.execute_batch([("SELECT content_json FROM book_contents WHERE content_version_id=?", (book["version"],)) for book in contents])
        inserts = []
        for book, cursor in zip(contents, cursors):
            inserts.append(("INSERT INTO books VALUES (?,?) ON CONFLICT(book_id) DO NOTHING", (book["id"], book["title"])))
            encoded = json.dumps(book, ensure_ascii=False, sort_keys=True)
            existing = cursor.fetchone()
            if existing and existing[0] != encoded:
                raise RuntimeError("콘텐츠 변경 시 새로운 version과 effective_at을 지정하세요.")
            inserts.append(("INSERT INTO book_contents VALUES (?,?,?,?) ON CONFLICT(content_version_id) DO NOTHING", (book["version"], book["id"], encoded, book["effective_at"])))
        db.execute_batch(inserts)
        db.commit()
    except Exception:
        db.rollback()
        raise



def register(app):
    from .services.cleanup import register as register_cleanup
    register_cleanup(app)
    from .services.seed import register as register_seed
    register_seed(app)

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
        db.begin_write()
        try:
            for table in ("reviews", "replies"):
                db.execute(f"UPDATE {table} SET body='',body_purged_at=? WHERE deleted_at IS NOT NULL AND deleted_at<? AND body_purged_at IS NULL", (utcnow(), cutoff))
            db.commit()
        except Exception:
            db.rollback()
            raise
        click.echo("삭제 상태 본문 폐기 완료. 기존 Export와 백업 사본에도 확정한 정책을 적용하세요.")
