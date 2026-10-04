import hmac
import json
import secrets

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..db import get_db
from ..queries import books
from ..services.event_logging import new_id, utcnow
from ..services.seed import available_invite, token_hash

bp = Blueprint('seed', __name__, url_prefix='/seed')


def signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='seed-onboarding')


def unavailable(status=400):
    return render_template('unavailable.html', message='이 초대 링크를 사용할 수 없습니다. 관리자에게 새 링크를 요청해주세요.'), status


@bp.before_request
def first_entry_only():
    if not current_app.config['LOCAL_DEVELOPMENT'] and not request.is_secure:
        return unavailable(403)
    # Never convert an existing visitor, including stale/unverifiable cookies.
    if 'visitor_id' in request.cookies:
        return render_template('unavailable.html', message='이미 참여한 브라우저에서는 초대를 사용할 수 없습니다. 처음 참여하는 별도 브라우저 프로필을 사용해주세요.'), 409


@bp.get('/<token>')
def onboard(token):
    if not available_invite(token):
        return unavailable()
    nonce = secrets.token_urlsafe(32)
    proof = signer().dumps({'hash': token_hash(token), 'nonce': nonce})
    response = current_app.make_response(render_template('seed_onboarding.html', token=token, proof=proof))
    response.set_cookie('seed_onboarding', nonce, max_age=600, httponly=True,
                        secure=not current_app.config['LOCAL_DEVELOPMENT'], samesite='Lax', path='/seed')
    return response


@bp.post('/activate')
def activate():
    token = request.form.get('token')
    digest = token_hash(token)
    nonce = request.cookies.get('seed_onboarding', '')
    # Chrome can send Origin: null for a form under no-referrer. The signed,
    # browser-bound nonce below is mandatory even for null/absent origins.
    if request.headers.get('Origin') and request.headers['Origin'] not in ('null', request.host_url.rstrip('/')):
        return unavailable(403)
    try:
        proof = signer().loads(request.form.get('proof', ''), max_age=600)
        if (not digest or not nonce or proof.get('hash') != digest or
                not hmac.compare_digest(proof.get('nonce', ''), nonce)):
            return unavailable(403)
    except (BadSignature, TypeError, AttributeError):
        return unavailable(403)
    db = get_db()
    db.begin_write()
    try:
        now = utcnow()
        consumed = db.execute('UPDATE seed_invites SET used_at=? WHERE token_hash=? '
                              'AND used_at IS NULL AND expires_at>?', (now, digest, now))
        if consumed.rowcount != 1:
            db.rollback()
            return unavailable()
        visitor = new_id()
        order = list(dict.fromkeys(b['id'] for b in books()))
        secrets.SystemRandom().shuffle(order)
        db.execute('INSERT INTO visitors VALUES (?,?,?,?,?,?)',
                   (visitor, now, json.dumps(order), 0, None, secrets.token_urlsafe(32)))
        db.execute('INSERT INTO seed_participants VALUES (?,?)', (visitor, now))
        db.commit()
    except Exception:
        db.rollback()
        raise
    visitor_signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='visitor-cookie')
    confirm = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='cookie-confirm')
    response = redirect(url_for('confirm_cookie', proof=confirm.dumps({'destination': '/'})), code=303)
    response.set_cookie('visitor_id', visitor_signer.dumps(visitor), max_age=30*86400,
                        httponly=True, secure=not current_app.config['LOCAL_DEVELOPMENT'], samesite='Lax')
    response.delete_cookie('seed_onboarding', path='/seed', secure=not current_app.config['LOCAL_DEVELOPMENT'], httponly=True, samesite='Lax')
    return response
