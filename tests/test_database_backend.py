import pytest

from app import create_app
from app.db import get_db, init_db
from app.db_backend import postgres_sql, Row
from scripts.build_vercel import build


def test_parameter_translation_preserves_quoted_question_marks():
    assert postgres_sql("SELECT ?, '?' AS literal, '50%' -- ?\n, ?") == "SELECT %s, '?' AS literal, '50%%' -- ?\n, %s"
    row = Row(["id", "body"], [1, "text"])
    assert row[0] == row["id"] == 1
    assert dict(row) == {"id": 1, "body": "text"}


@pytest.mark.parametrize("local,vercel", [(False, False), (True, True)])
def test_missing_production_url_never_creates_sqlite(tmp_path, local, vercel):
    path = tmp_path / "must-not-exist" / "database.sqlite"
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app({"DATABASE_URL": "", "DATABASE": str(path), "LOCAL_DEVELOPMENT": local, "VERCEL": vercel})
    assert not path.parent.exists()


def test_postgres_configuration_does_not_create_sqlite_directory(tmp_path):
    path = tmp_path / "must-not-exist" / "database.sqlite"
    create_app({"DATABASE_URL": "postgresql://example.invalid/database", "DATABASE": str(path),
                "LOCAL_DEVELOPMENT": True, "SECRET_KEY": "test", "VERCEL": True})
    assert not path.parent.exists()


def test_repeated_init_preserves_state_and_versions(app, participant):
    participant.action("emoji", option_id="0")
    with app.app_context():
        before = [dict(row) for row in get_db().execute("SELECT * FROM visitors")]
        versions = [dict(row) for row in get_db().execute("SELECT * FROM book_contents")]
        init_db()
        assert before == [dict(row) for row in get_db().execute("SELECT * FROM visitors")]
        assert versions == [dict(row) for row in get_db().execute("SELECT * FROM book_contents")]


def test_vercel_build_copies_only_static_assets(tmp_path):
    source = tmp_path / "app/static/images/books"
    source.mkdir(parents=True)
    (source / "scene.png").write_bytes(b"image")
    (tmp_path / ".env").write_text("secret")
    build(tmp_path)
    build(tmp_path)
    assert (tmp_path / "public/static/images/books/scene.png").read_bytes() == b"image"
    assert not (tmp_path / "public/.env").exists()
