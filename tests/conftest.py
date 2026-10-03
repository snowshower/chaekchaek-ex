import json
import re
from html import unescape
from uuid import uuid4

import pytest

from app import create_app
from app.db import get_db, init_db
from app.services.event_logging import utcnow


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite"), "SECRET_KEY": "test-secret", "LOCAL_DEVELOPMENT": True, "EXPOSURE_POLICY": "cards", "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "test-password", "EXPERIMENT_START": "", "EXPERIMENT_END": ""})
    with app.app_context():
        init_db()
    return app


class Participant:
    def __init__(self, app, book_id="metamorphosis"):
        self.app = app
        self.client = app.test_client()
        self.sequence = 0
        self.open(book_id)

    def open(self, book_id="metamorphosis", landing=False):
        self.book_id = None if landing else book_id
        response = self.client.get("/" if landing else f"/books/{book_id}", follow_redirects=True)
        assert response.status_code == 200
        self.bootstrap = json.loads(unescape(re.search(r"data-json='(.*?)'", response.get_data(as_text=True)).group(1)))
        self.sequence = 0
        self.action("observe", event_type="landing_view" if landing else "book_view")
        return response

    def payload(self, operation, **fields):
        self.sequence += 1
        return {"event_id": str(uuid4()), "page_view_id": self.bootstrap["page_view_id"], "client_occurred_at": utcnow(), "client_sequence": self.sequence, "operation": operation, **fields}

    def post(self, payload):
        return self.client.post("/api/actions", json=payload, headers={"X-CSRF-Token": self.bootstrap["csrf"]})

    def action(self, operation, **fields):
        response = self.post(self.payload(operation, **fields))
        assert response.status_code == 200, response.json
        return response.json

    def state(self):
        return self.client.get(f"/api/books/{self.book_id}/state", query_string={"page_view_id": self.bootstrap["page_view_id"]}).json

    def expose(self, target, source="community_open", area="community_reviews", kind="others_reveal"):
        return self.action("observe", event_type=kind, target_id=target, reveal_source=source, exposure_area=area, active_tab=True, visibility_ratio=.5)

    def visitor_id(self):
        with self.app.app_context():
            return get_db().execute("SELECT visitor_id FROM page_views WHERE page_view_id=?", (self.bootstrap["page_view_id"],)).fetchone()[0]


@pytest.fixture
def participant(app):
    return Participant(app)


def rows(app, table, where="1=1", args=()):
    with app.app_context():
        return [dict(r) for r in get_db().execute(f"SELECT * FROM {table} WHERE {where}", args)]
