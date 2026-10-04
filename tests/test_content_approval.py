import json
from copy import deepcopy
from pathlib import Path

import pytest

import app as app_module
import app.db as db_module
from app import create_app
from app.db import get_db, init_db
from app.queries import book
from conftest import Participant


ROOT = Path(__file__).resolve().parents[1]
CONTENTS = json.loads((ROOT / 'data/books.json').read_text(encoding='utf-8'))


def production_config():
    return dict(DATABASE_URL='postgresql://example.invalid/database', VERCEL=False,
                LOCAL_DEVELOPMENT=False, SECRET_KEY='test-secret',
                OPERATIONS_CONFIRMED=True, NOTICE_TEXT='test notice',
                EXPERIMENT_START='2026-01-01T00:00:00Z', EXPERIMENT_END='',
                EXPOSURE_POLICY='cards')


def test_approved_content_still_requires_operations_confirmation():
    create_app(production_config())
    with pytest.raises(RuntimeError):
        create_app(dict(production_config(), OPERATIONS_CONFIRMED=False))


@pytest.mark.parametrize('index', range(len(CONTENTS)))
@pytest.mark.parametrize('field,value', [('source', ''), ('translation', ''),
                                        ('usage_status', 'pending')])
def test_gate_checks_every_content_version(tmp_path, monkeypatch, index, field, value):
    contents = deepcopy(CONTENTS)
    contents[index][field] = value
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/books.json').write_text(json.dumps(contents), encoding='utf-8')
    monkeypatch.setattr(app_module, 'ROOT', tmp_path)
    with pytest.raises(RuntimeError):
        create_app(production_config())


def test_approval_preserves_stored_history_and_open_page(app, tmp_path, monkeypatch):
    legacy = deepcopy(CONTENTS)
    for content in legacy:
        content['version'] = content['version'].removesuffix('-approved')
        content.update(source='', translation='', usage_status='pending',
                       effective_at='2026-10-01T00:00:00.000000Z')
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/books.json'
    path.write_text(json.dumps(legacy), encoding='utf-8')
    monkeypatch.setattr(db_module, 'ROOT', tmp_path)
    # The normal schema is unchanged; only the content manifest is substituted.
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app/schema.sql').write_bytes((ROOT / 'app/schema.sql').read_bytes())
    with app.app_context():
        get_db().execute('DELETE FROM book_contents')
        init_db()
        before = [tuple(row) for row in get_db().execute(
            "SELECT * FROM book_contents WHERE content_version_id NOT LIKE '%-approved' ORDER BY content_version_id")]
    participant = Participant(app)
    with app.app_context():
        old_version = 'metamorphosis-v2'
        assert get_db().execute('SELECT content_version_id FROM page_views WHERE page_view_id=?',
                                (participant.bootstrap['page_view_id'],)).fetchone()[0] == old_version
    path.write_text(json.dumps(CONTENTS), encoding='utf-8')
    with app.app_context():
        init_db()
        init_db()
        after = [tuple(row) for row in get_db().execute(
            "SELECT * FROM book_contents WHERE content_version_id NOT LIKE '%-approved' ORDER BY content_version_id")]
        assert before == after
        assert book('metamorphosis')['version'] == 'metamorphosis-v2-approved'
        assert book('metamorphosis', old_version)['usage_status'] == 'pending'
        for current, previous in zip(CONTENTS, legacy):
            assert {k: v for k, v in current.items() if k not in
                    ('source', 'translation', 'usage_status', 'version', 'effective_at')} == {
                        k: v for k, v in previous.items() if k not in
                        ('source', 'translation', 'usage_status', 'version', 'effective_at')}
        changed = deepcopy(CONTENTS)
        changed[0]['source'] = 'changed'
        path.write_text(json.dumps(changed), encoding='utf-8')
        with pytest.raises(RuntimeError):
            init_db()
    participant.action('emoji', option_id='0')
    with app.app_context():
        assert get_db().execute('SELECT content_version_id FROM emoji_reactions').fetchone()[0] == old_version
