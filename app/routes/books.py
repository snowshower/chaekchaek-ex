import json

from flask import Blueprint, abort, current_app, g, render_template, request

from ..db import get_db
from ..queries import book
from ..services.event_logging import new_id, utcnow
from ..services.participation import state

bp = Blueprint("books", __name__)


def create_page(book_id=None, version=None, order=None, source=None):
    page_id = new_id()
    get_db().execute("INSERT INTO page_views VALUES (?,?,?,?,?,?,?)", (page_id, g.visitor["visitor_id"], book_id, version, json.dumps(order) if order else None, source, utcnow()))
    return {"page_view_id": page_id, "book_id": book_id, "version": version, "csrf": g.visitor["csrf_token"], "exposure_policy": current_app.config["EXPOSURE_POLICY"]}


@bp.get("/")
def landing():
    order = json.loads(g.visitor["landing_book_order"])
    return render_template("landing.html", books=[book(b) for b in order], bootstrap=create_page(order=order))


@bp.get("/books/<book_id>")
def detail(book_id):
    content = book(book_id)
    if not content:
        abort(404)
    selected = request.args.get("selection")
    if selected:
        event = get_db().execute("SELECT 1 FROM events WHERE event_id=? AND visitor_id=? AND book_id=? AND event_type='book_select'", (selected, g.visitor["visitor_id"], book_id)).fetchone()
        if not event:
            selected = None
    return render_template("book.html", book=content, bootstrap=create_page(book_id, content["version"], source=selected))


@bp.get("/api/books/<book_id>/state")
def get_state(book_id):
    page = get_db().execute("SELECT * FROM page_views WHERE page_view_id=? AND visitor_id=? AND book_id=?", (request.args.get("page_view_id"), g.visitor["visitor_id"], book_id)).fetchone()
    if not page:
        abort(403)
    return state(book_id, page["content_version_id"])
