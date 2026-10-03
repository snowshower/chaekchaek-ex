import hmac
import json
import secrets
from uuid import UUID
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, jsonify, make_response, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import ROOT, settings
from .db import get_db, register, IntegrityError, OperationalError, validate_configuration
from .services.event_logging import PolicyError, new_id, utcnow, validate_utc


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(settings())
    app.config.update(config or {})
    validate_configuration(app.config)
    # The formerly undecided policy is now cards, including old shell settings.
    # .env.example changes cannot update an already exported environment value.
    if app.config["EXPOSURE_POLICY"] in ("pending", ""):
        app.config["EXPOSURE_POLICY"] = "cards"
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY 환경변수를 설정하세요.")
    app.config["SESSION_COOKIE_SECURE"] = not app.config["LOCAL_DEVELOPMENT"]
    for key in ("EXPERIMENT_START", "EXPERIMENT_END"):
        if app.config[key]:
            app.config[key] = validate_utc(app.config[key])
    if app.config["EXPERIMENT_END"] and (not app.config["EXPERIMENT_START"] or app.config["EXPERIMENT_END"] <= app.config["EXPERIMENT_START"]):
        raise RuntimeError("종료 시각은 시작 시각 이후여야 합니다.")
    if not app.config["LOCAL_DEVELOPMENT"]:
        if not app.config["OPERATIONS_CONFIRMED"] or not app.config["NOTICE_TEXT"] or not app.config["EXPERIMENT_START"] or app.config["EXPOSURE_POLICY"] != "cards":
            raise RuntimeError("운영 전 시작 시각·고지·보관 정책·노출 정책을 확정하세요.")
        content = json.loads((ROOT / "data/books.json").read_text(encoding="utf-8"))
        if any(not b["source"] or not b["translation"] or b["usage_status"] != "approved" for b in content):
            raise RuntimeError("운영 전 콘텐츠 출처·번역본·사용 가능 여부(approved)를 확정하세요.")
    try:
        display_zone = ZoneInfo(app.config["DISPLAY_TIMEZONE"])
    except ZoneInfoNotFoundError:
        raise RuntimeError("DISPLAY_TIMEZONE의 IANA 시간대 또는 tzdata 설치를 확인하세요.") from None

    @app.template_filter("localtime")
    def localtime(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(display_zone).isoformat(timespec="seconds") if value else "—"
    register(app)
    signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="visitor-cookie")
    confirm_signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="cookie-confirm")

    @app.before_request
    def identify():
        if request.endpoint is None or request.endpoint == "static" or request.path.startswith("/admin"):
            return
        g.visitor = None
        admin_browser = False
        try:
            admin_browser = signer.loads(request.cookies.get("admin_test", ""), max_age=30*86400) == "admin"
        except BadSignature:
            pass
        token = request.cookies.get("visitor_id")
        if token:
            try:
                visitor_id = signer.loads(token, max_age=30 * 86400)
                if not isinstance(visitor_id, str):
                    raise ValueError()
                UUID(visitor_id)
                g.visitor = get_db().execute("SELECT * FROM visitors WHERE visitor_id=?", (visitor_id,)).fetchone()
            except (BadSignature, ValueError, TypeError):
                pass
        if request.endpoint == "confirm_cookie":
            return
        if not g.visitor:
            if request.path.startswith("/api/"):
                return jsonify(error="쿠키 유지 확인 후에만 참여할 수 있습니다."), 403
            visitor_id = new_id()
            from .queries import books
            order = list(dict.fromkeys(b["id"] for b in books()))
            secrets.SystemRandom().shuffle(order)
            local_test = app.config["LOCAL_DEVELOPMENT"] and not app.config["TESTING"]
            is_test = admin_browser or local_test
            reason = "admin browser" if admin_browser else "local development" if local_test else None
            get_db().execute("INSERT INTO visitors VALUES (?,?,?,?,?,?)", (visitor_id, utcnow(), json.dumps(order), int(is_test), reason, secrets.token_urlsafe(32)))
            destination = request.full_path.rstrip("?")
            proof = confirm_signer.dumps({"destination": destination})
            response = redirect(url_for("confirm_cookie", proof=proof))
            response.set_cookie("visitor_id", signer.dumps(visitor_id), max_age=30 * 86400, httponly=True, secure=not app.config["LOCAL_DEVELOPMENT"], samesite="Lax")
            return response
        if admin_browser and not g.visitor["is_test"]:
            get_db().execute("UPDATE visitors SET is_test=1,exclusion_reason='admin browser' WHERE visitor_id=?", (g.visitor["visitor_id"],))
        if request.path.startswith("/api/") and request.method != "GET":
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), g.visitor["csrf_token"].encode()):
                return jsonify(error="페이지를 새로 연 후 다시 시도해주세요."), 403
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                return jsonify(error="다른 사이트의 쓰기 요청은 허용하지 않습니다."), 403
            end = app.config["EXPERIMENT_END"]
            if end and utcnow() >= end:
                return jsonify(error="실험이 종료되었습니다."), 403
            start = app.config["EXPERIMENT_START"]
            if not app.config["LOCAL_DEVELOPMENT"] and start and utcnow() < start:
                return jsonify(error="아직 실험 시작 전입니다."), 403

    @app.get("/_cookie-confirm")
    def confirm_cookie():
        try:
            proof = confirm_signer.loads(request.args.get("proof", ""), max_age=300)
            destination = proof["destination"]
            if not destination.startswith("/") or destination.startswith("//"):
                raise ValueError()
            if g.visitor:
                return redirect(destination)
        except (BadSignature, ValueError, KeyError, TypeError):
            pass
        return render_template("unavailable.html", message="브라우저에서 쿠키를 유지할 수 없어 참여할 수 없습니다. 쿠키를 허용한 뒤 처음 페이지를 다시 열어주세요."), 403

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if not app.config["LOCAL_DEVELOPMENT"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(PolicyError)
    def policy_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(OperationalError)
    def busy(error):
        diagnostic = getattr(error, "diagnostic", None)
        if diagnostic:
            app.logger.error("%s", diagnostic)
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            return jsonify(error="저장이 잠시 지연되었습니다. 같은 요청으로 다시 시도해주세요."), 503
        if not diagnostic:
            app.logger.error("Database operation failed")
        return jsonify(error="저장에 실패했습니다. 입력을 유지하고 다시 시도해주세요."), 500

    @app.errorhandler(IntegrityError)
    def integrity(_error):
        return jsonify(error="요청 순서 또는 식별자가 충돌했습니다. 페이지를 새로 열어주세요."), 409

    from .routes.books import bp as books_bp
    from .routes.events import bp as events_bp
    from .routes.admin import bp as admin_bp
    app.register_blueprint(books_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(admin_bp)
    return app
