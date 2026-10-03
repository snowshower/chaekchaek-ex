import hashlib
import json

from flask import current_app, g

from ..db import get_db
from ..queries import book, first_event
from .event_logging import PolicyError, new_id, observed_once, record, utcnow, uuid, validate_utc


def identity():
    return g.visitor["visitor_id"]


def public_cohort():
    """Only local test browsers can access the isolated test community."""
    return int(current_app.config["LOCAL_DEVELOPMENT"] and g.visitor["is_test"])


def eligibility(book_id):
    rows = get_db().execute("SELECT * FROM events WHERE visitor_id=? AND book_id=? AND event_type IN (?,?,?,?) ORDER BY timestamp,event_id", (identity(), book_id, "emoji_reaction", "poll_vote", "short_review_submit", "community_open")).fetchall()
    return eligibility_rows(rows)


def eligibility_rows(rows):
    names = {"emoji_reaction": "emoji", "poll_vote": "poll", "short_review_submit": "short", "community_open": "community"}
    result = dict.fromkeys(names.values())
    for row in rows:
        key = names[row["event_type"]]
        if result[key] is None:
            result[key] = row
    return result


def require_community(book_id):
    if not eligibility(book_id)["community"]:
        raise PolicyError("먼저 다른 사람들의 감상 보기로 커뮤니티를 열어주세요.", 403)


def public_reviews(book_id, kind, community=False):
    db = get_db()
    rows = db.execute("SELECT r.* FROM reviews r JOIN visitors v ON v.visitor_id=r.visitor_id WHERE r.book_id=? AND r.review_type=? AND r.deleted_at IS NULL AND v.is_test=? ORDER BY r.first_submitted_at DESC,r.review_id DESC", (book_id, kind, public_cohort())).fetchall()
    result = []
    for r in rows:
        # No visitor IDs or private deleted bodies in public responses.
        entry = {"id": r["review_id"], "type": kind, "body": r["body"], "mine": r["visitor_id"] == identity(), "created_at": r["first_submitted_at"]}
        if community:
            entry["likes"] = db.execute("SELECT count(*) FROM likes l JOIN visitors v ON v.visitor_id=l.visitor_id WHERE review_id=? AND cancelled_at IS NULL AND v.is_test=?", (r["review_id"], public_cohort())).fetchone()[0]
            entry["liked"] = bool(db.execute("SELECT 1 FROM likes WHERE visitor_id=? AND review_id=? AND cancelled_at IS NULL", (identity(), r["review_id"])).fetchone())
            entry["replies"] = [{"id": t["reply_id"], "body": t["body"], "mine": t["visitor_id"] == identity(), "created_at": t["first_submitted_at"]} for t in db.execute("SELECT t.* FROM replies t JOIN visitors v ON v.visitor_id=t.visitor_id WHERE t.review_id=? AND t.deleted_at IS NULL AND v.is_test=? ORDER BY t.first_submitted_at,t.reply_id", (r["review_id"], public_cohort()))]
        result.append(entry)
    return result


def state(book_id, version=None):
    db = get_db()
    cursors = db.execute_batch([
        ("SELECT * FROM events WHERE visitor_id=? AND book_id=? AND event_type IN (?,?,?,?) ORDER BY timestamp,event_id", (identity(), book_id, "emoji_reaction", "poll_vote", "short_review_submit", "community_open")),
        ("SELECT 'emoji' AS kind,option_id,cancelled_at FROM emoji_reactions WHERE visitor_id=? AND book_id=? UNION ALL SELECT 'poll',option_id,cancelled_at FROM poll_votes WHERE visitor_id=? AND book_id=?", (identity(), book_id, identity(), book_id)),
        ("SELECT * FROM reviews WHERE visitor_id=? AND book_id=?", (identity(), book_id)),
        ("SELECT 'emoji' AS kind,x.option_id,count(*) AS count FROM emoji_reactions x JOIN visitors v ON x.visitor_id=v.visitor_id WHERE x.book_id=? AND x.cancelled_at IS NULL AND v.is_test=? GROUP BY x.option_id UNION ALL SELECT 'poll',x.option_id,count(*) FROM poll_votes x JOIN visitors v ON x.visitor_id=v.visitor_id WHERE x.book_id=? AND x.cancelled_at IS NULL AND v.is_test=? GROUP BY x.option_id", (book_id, public_cohort(), book_id, public_cohort())),
    ])
    rights = eligibility_rows(cursors[0].fetchall())
    choices = {row["kind"]: row for row in cursors[1]}
    own_reviews = {row["review_type"]: row for row in cursors[2]}
    all_counts = list(cursors[3])
    content = book(book_id, version) if rights["emoji"] or rights["poll"] else None
    result = {"community_open": bool(rights["community"]), "entitlements": {k: bool(v) for k, v in rights.items()}, "causes": {k: v["event_id"] if v else None for k, v in rights.items()}, "origins": {k: v["page_view_id"] if v else None for k, v in rights.items()}, "own_reviews": {}}
    for kind, table in (("emoji", "emoji_reactions"), ("poll", "poll_votes")):
        own = choices.get(kind)
        result[kind + "_selection"] = own["option_id"] if own and not own["cancelled_at"] else None
        if rights[kind]:
            counts = {r["option_id"]: r["count"] for r in all_counts if r["kind"] == kind}
            total = sum(counts.values())
            result[kind + "_results"] = [{"option_id": str(i), "label": label, "count": counts.get(str(i), 0), "ratio": counts.get(str(i), 0) / total if total else None} for i, label in enumerate(content[kind + "_options"])]
    for kind in ("short", "full"):
        row = own_reviews.get(kind)
        result["own_reviews"][kind] = {"id": row["review_id"], "body": row["body"] if not row["deleted_at"] else "", "deleted": bool(row["deleted_at"])} if row else None
    if rights["short"] or rights["community"]:
        result["short_reviews"] = public_reviews(book_id, "short")
    if rights["community"]:
        result["community"] = {kind: public_reviews(book_id, kind, True) for kind in ("short", "full")}
    return result


def validated_body(payload, maximum):
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        raise PolicyError("공백만 있는 글은 등록할 수 없습니다.")
    if len(body) > maximum:
        raise PolicyError(f"최대 {maximum}자까지 작성할 수 있습니다.")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in body):
        raise PolicyError("올바르지 않은 Unicode 문자입니다.")
    return body


def target_review(book_id, review_id):
    row = get_db().execute("SELECT r.* FROM reviews r JOIN visitors v ON v.visitor_id=r.visitor_id WHERE r.review_id=? AND r.book_id=? AND r.deleted_at IS NULL AND v.is_test=?", (review_id, book_id, public_cohort())).fetchone()
    if not row or row["visitor_id"] == identity():
        raise PolicyError("상호작용할 수 없는 감상입니다.", 403)
    return row


def selection(payload, page, kind):
    db, now = get_db(), utcnow()
    table, id_column, first_column, event = ("emoji_reactions", "reaction_id", "first_selected_at", "emoji_reaction") if kind == "emoji" else ("poll_votes", "vote_id", "first_voted_at", "poll_vote")
    option = payload.get("option_id")
    content = book(page["book_id"], page["content_version_id"])
    if option is not None and option not in [str(i) for i in range(len(content[kind + "_options"]))]:
        raise PolicyError("선택지가 올바르지 않습니다.")
    old = db.execute(f"SELECT * FROM {table} WHERE visitor_id=? AND book_id=?", (identity(), page["book_id"])).fetchone()
    previous = old["option_id"] if old and not old["cancelled_at"] else None
    if option == previous:
        return
    target_id = old[id_column] if old else new_id()
    if old:
        db.execute(f"UPDATE {table} SET option_id=?,updated_at=?,cancelled_at=?,content_version_id=? WHERE {id_column}=?", (option, now, now if option is None else None, page["content_version_id"], target_id))
    else:
        db.execute(f"INSERT INTO {table} ({id_column},visitor_id,book_id,option_id,content_version_id,{first_column},updated_at) VALUES (?,?,?,?,?,?,?)", (target_id, identity(), page["book_id"], option, page["content_version_id"], now, now))
    record(payload, kind + "_cancel" if option is None else event, target_type=kind, target_id=target_id, option_id=option, previous_option_id=previous, action=None if option is None else ("change" if previous is not None else "select"))


def review(payload, page, kind):
    db, now = get_db(), utcnow()
    if kind == "full":
        require_community(page["book_id"])
    old = db.execute("SELECT * FROM reviews WHERE visitor_id=? AND book_id=? AND review_type=?", (identity(), page["book_id"], kind)).fetchone()
    delete = payload.get("delete", False)
    if delete:
        if not old or old["deleted_at"]:
            return
        db.execute("UPDATE reviews SET deleted_at=?,updated_at=? WHERE review_id=?", (now, now, old["review_id"]))
        record(payload, kind + "_review_delete", target_type="review", target_id=old["review_id"])
        return
    body = validated_body(payload, 150 if kind == "short" else 2000)
    if old and not old["deleted_at"] and old["body"] == body:
        return
    target_id = old["review_id"] if old else new_id()
    if old:
        db.execute("UPDATE reviews SET body=?,updated_at=?,deleted_at=NULL,body_purged_at=NULL,content_version_id=? WHERE review_id=?", (body, now, page["content_version_id"], target_id))
    else:
        db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,NULL,NULL)", (target_id, identity(), page["book_id"], kind, body, page["content_version_id"], now, now))
    record(payload, kind + "_review_" + ("update" if old else "submit"), target_type="review", target_id=target_id, body_length=len(body), action=("restore" if old["deleted_at"] else "edit") if old else None)


def like(payload, page):
    db, now = get_db(), utcnow()
    require_community(page["book_id"])
    target = target_review(page["book_id"], payload.get("target_id"))
    active = payload.get("active")
    if not isinstance(active, bool):
        raise PolicyError("좋아요 상태가 올바르지 않습니다.")
    old = db.execute("SELECT * FROM likes WHERE visitor_id=? AND review_id=?", (identity(), target["review_id"])).fetchone()
    if active == bool(old and not old["cancelled_at"]):
        return
    target_id = old["like_id"] if old else new_id()
    if old:
        db.execute("UPDATE likes SET cancelled_at=?,updated_at=? WHERE like_id=?", (None if active else now, now, target_id))
    else:
        db.execute("INSERT INTO likes VALUES (?,?,?,?,?,NULL)", (target_id, identity(), target["review_id"], now, now))
    record(payload, "like" if active else "like_cancel", target_type="review", target_id=target["review_id"])


def reply(payload, page):
    db, now = get_db(), utcnow()
    require_community(page["book_id"])
    reply_id = payload.get("reply_id")
    old = db.execute("SELECT t.*,r.book_id FROM replies t JOIN reviews r ON r.review_id=t.review_id WHERE t.reply_id=?", (reply_id,)).fetchone() if reply_id else None
    if reply_id and (not old or old["visitor_id"] != identity() or old["book_id"] != page["book_id"] or old["deleted_at"]):
        raise PolicyError("수정할 수 없는 답글입니다.", 403)
    if payload.get("delete"):
        if not old:
            raise PolicyError("답글을 확인할 수 없습니다.")
        db.execute("UPDATE replies SET deleted_at=?,updated_at=? WHERE reply_id=?", (now, now, reply_id))
        record(payload, "reply_delete", target_type="reply", target_id=reply_id)
        return
    target = target_review(page["book_id"], old["review_id"] if old else payload.get("target_id"))
    body = validated_body(payload, 300)
    if old and old["body"] == body:
        return
    if old:
        db.execute("UPDATE replies SET body=?,updated_at=? WHERE reply_id=?", (body, now, reply_id))
    else:
        reply_id = new_id()
        db.execute("INSERT INTO replies VALUES (?,?,?,?,?,?,NULL,NULL)", (reply_id, identity(), target["review_id"], body, now, now))
    record(payload, "reply_update" if old else "reply_submit", target_type="reply", target_id=reply_id, body_length=len(body))


def reveal_metadata(payload, page):
    rights = eligibility(page["book_id"])
    area, source = payload.get("exposure_area"), payload.get("reveal_source")
    if area == "community_reviews":
        require_community(page["book_id"])
        current = get_db().execute("SELECT event_id FROM events WHERE page_view_id=? AND event_type='community_open'", (page["page_view_id"],)).fetchone()
        expected, cause = ("community_open", current[0]) if current else ("community_restore", rights["community"]["event_id"])
    elif area == "individual_short_reviews" and (rights["short"] or rights["community"]):
        current_short = get_db().execute("SELECT event_id FROM events WHERE page_view_id=? AND event_type='short_review_submit'", (page["page_view_id"],)).fetchone()
        if current_short:
            expected, cause = "short_review_submit", current_short[0]
        elif rights["short"]:
            expected, cause = "return_visit", rights["short"]["event_id"]
        else:
            current = get_db().execute("SELECT event_id FROM events WHERE page_view_id=? AND event_type='community_open'", (page["page_view_id"],)).fetchone()
            expected, cause = ("community_open", current[0]) if current else ("community_restore", rights["community"]["event_id"])
    else:
        raise PolicyError("공개되지 않은 감상 영역입니다.", 403)
    if source != expected:
        raise PolicyError("공개 경로가 일치하지 않습니다.")
    target = get_db().execute("SELECT r.* FROM reviews r JOIN visitors v ON r.visitor_id=v.visitor_id WHERE r.review_id=? AND r.book_id=? AND r.visitor_id<>? AND r.deleted_at IS NULL AND v.is_test=?", (payload.get("target_id"), page["book_id"], identity(), public_cohort())).fetchone()
    if not target or (area == "individual_short_reviews" and target["review_type"] != "short"):
        raise PolicyError("실제 타인 감상을 확인할 수 없습니다.")
    return {"reveal_source": source, "exposure_area": area, "cause_event_id": cause, "target_type": "review", "target_id": target["review_id"]}, target


def observe(payload, page):
    kind, db = payload.get("event_type"), get_db()
    if page["book_id"] is None:
        if kind == "landing_view":
            observed_once(payload, kind, displayed_book_order=page["displayed_book_order"])
        elif kind == "book_select":
            order = json.loads(page["displayed_book_order"])
            selected = payload.get("book_id")
            if selected not in order or payload.get("display_position") != order.index(selected) + 1:
                raise PolicyError("실제 랜딩 위치와 선택이 일치하지 않습니다.")
            if not db.execute("SELECT 1 FROM events WHERE page_view_id=? AND event_type='landing_view'", (page["page_view_id"],)).fetchone():
                raise PolicyError("랜딩 표시를 먼저 확인해야 합니다.")
            record(payload, kind, book_id=selected, landing_page_view_id=page["page_view_id"], display_position=payload["display_position"])
        else:
            raise PolicyError("랜딩 이벤트가 아닙니다.")
        return
    if kind == "book_view":
        observed_once(payload, kind, source_book_select_event_id=page["source_book_select_event_id"])
        return
    rights = eligibility(page["book_id"])
    if not db.execute("SELECT 1 FROM events WHERE page_view_id=? AND event_type='book_view'", (page["page_view_id"],)).fetchone():
        raise PolicyError("도서 표시를 먼저 확인해야 합니다.")
    if kind == "community_open":
        # Automatically restored access never emits a new direct-open event.
        if not rights["community"]:
            observed_once(payload, kind)
    elif kind in ("excerpt_view", "emoji_results_reveal", "poll_results_reveal", "short_reviews_reveal", "others_reveal"):
        if current_app.config["EXPOSURE_POLICY"] != "cards":
            raise PolicyError("노출 정책은 cards여야 합니다.", 409)
        ratio = payload.get("visibility_ratio")
        if type(ratio) not in (int, float) or not .5 <= ratio <= 1 or payload.get("active_tab") is not True:
            raise PolicyError("활성 탭 50% 노출이 필요합니다.")
        if kind == "excerpt_view":
            observed_once(payload, kind)
        elif kind in ("emoji_results_reveal", "poll_results_reveal"):
            right = rights[kind.split("_")[0]]
            if not right:
                raise PolicyError("결과 공개 자격이 없습니다.", 403)
            observed_once(payload, kind, cause_event_id=right["event_id"])
        else:
            metadata, target = reveal_metadata(payload, page)
            if kind == "short_reviews_reveal" and target["review_type"] != "short":
                raise PolicyError("타인 한 줄 감상이어야 합니다.")
            observed_once(payload, kind, **metadata)
    elif kind in ("short_review_start", "full_review_start"):
        review_type = kind.split("_")[0]
        if review_type == "full":
            require_community(page["book_id"])
        if not first_event(identity(), page["book_id"], review_type + "_review_submit"):
            observed_once(payload, kind)
    elif kind == "reply_start":
        require_community(page["book_id"])
        target_review(page["book_id"], payload.get("target_id"))
        observed_once(payload, kind, target_type="review", target_id=payload["target_id"])
    else:
        raise PolicyError("허용되지 않은 관측 이벤트입니다.")


def execute(payload):
    if not isinstance(payload, dict):
        raise PolicyError("JSON 요청이 필요합니다.")
    uuid(payload.get("event_id")); uuid(payload.get("page_view_id"))
    validate_utc(payload.get("client_occurred_at"))
    sequence = payload.get("client_sequence")
    if type(sequence) is not int or not 1 <= sequence <= 2147483647:
        raise PolicyError("페이지 관측 순서가 필요합니다.")
    for field in ("target_id", "reply_id"):
        if field in payload:
            uuid(payload[field])
    if "delete" in payload and type(payload["delete"]) is not bool:
        raise PolicyError("삭제 상태가 올바르지 않습니다.")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    db = get_db()
    # Completed UUIDs need no write lock. A miss is rechecked after acquiring it.
    db.begin_read()
    try:
        existing = db.execute("SELECT * FROM requests WHERE event_id=?", (payload["event_id"],)).fetchone()
        page = db.execute("SELECT * FROM page_views WHERE page_view_id=? AND visitor_id=?", (payload["page_view_id"], identity())).fetchone()
        if existing:
            response = replay(existing, fingerprint, page)
            db.commit()
            return response
        if page and payload.get("operation") != "observe":
            if not page["book_id"] or not db.execute("SELECT 1 FROM events WHERE page_view_id=? AND event_type='book_view'", (page["page_view_id"],)).fetchone():
                raise PolicyError("도서 표시를 먼저 확인해야 합니다.", 403)
            if payload.get("operation") in ("emoji", "poll"):
                book(page["book_id"], page["content_version_id"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not page:
        raise PolicyError("현재 페이지를 확인할 수 없습니다.", 403)
    g.action_page = page
    db.begin_write()
    try:
        existing = db.execute("SELECT * FROM requests WHERE event_id=?", (payload["event_id"],)).fetchone()
        if existing:
            if existing["visitor_id"] != identity() or existing["fingerprint"] != fingerprint:
                raise PolicyError("같은 event_id에 다른 요청을 사용할 수 없습니다.", 409)
            response = json.loads(existing["response_json"])
            db.commit()
            return response_state(response, page)
        if not page:
            raise PolicyError("현재 페이지를 확인할 수 없습니다.", 403)
        action = payload.get("operation")
        if action == "observe":
            observe(payload, page)
        else:
            if action in ("emoji", "poll"):
                selection(payload, page, action)
            elif action in ("short", "full"):
                review(payload, page, action)
            elif action == "like":
                like(payload, page)
            elif action == "reply":
                reply(payload, page)
            else:
                raise PolicyError("허용되지 않은 작업입니다.")
        response = {"ok": True, "event_id": payload["event_id"]}
        db.execute("INSERT INTO requests VALUES (?,?,?,?)", (payload["event_id"], identity(), fingerprint, json.dumps(response)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response_state(response, page)


def replay(existing, fingerprint, page):
    if existing["visitor_id"] != identity() or existing["fingerprint"] != fingerprint:
        raise PolicyError("같은 event_id에 다른 요청을 사용할 수 없습니다.", 409)
    response = json.loads(existing["response_json"])
    if page and page["book_id"]:
        response["state"] = state(page["book_id"], page["content_version_id"])
    return response


def response_state(response, page):
    if page["book_id"]:
        db = get_db()
        db.begin_read()
        try:
            response["state"] = state(page["book_id"], page["content_version_id"])
            db.commit()
        except Exception:
            db.rollback()
            raise
    return response
