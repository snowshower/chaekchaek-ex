from flask import Blueprint, request

from ..services.participation import execute

bp = Blueprint("events", __name__)


@bp.post("/api/actions")
def action():
    return execute(request.get_json(silent=True))
