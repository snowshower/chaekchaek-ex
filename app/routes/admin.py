import hmac
import io
from functools import wraps

from flask import Blueprint, Response, current_app, render_template, request, send_file

from ..db import get_db
from ..services.reporting import export_zip, report

bp = Blueprint("admin", __name__, url_prefix="/admin")


def authenticated(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not current_app.config["LOCAL_DEVELOPMENT"] and not request.is_secure:
            return Response("HTTPS가 필요합니다.", 403)
        auth = request.authorization
        user, password = current_app.config["ADMIN_USERNAME"], current_app.config["ADMIN_PASSWORD"]
        if not user or not password:
            return Response("관리자 인증 설정이 필요합니다.", 503)
        if not auth or auth.type.lower() != "basic" or not hmac.compare_digest((auth.username or "").encode(), user.encode()) or not hmac.compare_digest((auth.password or "").encode(), password.encode()):
            return Response("관리자 인증이 필요합니다.", 401, {"WWW-Authenticate": 'Basic realm="Experiment", charset="UTF-8"'})
        return function(*args, **kwargs)
    return wrapped


@bp.get("")
@bp.get("/")
@authenticated
def dashboard():
    db = get_db()
    db.begin_read()
    try:
        data = report()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return render_template("admin.html", report=data)


@bp.get("/export")
@authenticated
def export():
    return send_file(io.BytesIO(export_zip()), mimetype="application/zip", as_attachment=True, download_name="experiment-export.zip")
