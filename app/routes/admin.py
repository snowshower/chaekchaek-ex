import hmac
import io
from functools import wraps

from flask import Blueprint, Response, current_app, make_response, render_template, request, send_file

from ..db import get_db
from ..services.reporting import export_zip, report, test_report

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
        # Visiting admin with a previously issued participant cookie excludes that browser's whole history.
        from itsdangerous import BadSignature, URLSafeTimedSerializer
        try:
            visitor = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="visitor-cookie").loads(request.cookies.get("visitor_id", ""), max_age=30*86400)
            get_db().execute("UPDATE visitors SET is_test=1,exclusion_reason=coalesce(exclusion_reason,'admin browser') WHERE visitor_id=?", (visitor,))
        except BadSignature:
            pass
        response = make_response(function(*args, **kwargs))
        token = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="visitor-cookie").dumps("admin")
        response.set_cookie("admin_test", token, max_age=30*86400, httponly=True, secure=not current_app.config["LOCAL_DEVELOPMENT"], samesite="Lax")
        return response
    return wrapped


@bp.get("")
@bp.get("/")
@authenticated
def dashboard():
    db = get_db()
    db.begin_read()
    try:
        data = report()
        test_data = test_report()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return render_template("admin.html", report=data, test_report=test_data)


@bp.get("/export")
@authenticated
def export():
    return send_file(io.BytesIO(export_zip()), mimetype="application/zip", as_attachment=True, download_name="experiment-export.zip")
