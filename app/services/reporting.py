import csv
import io
import json
import zipfile
from collections import Counter

from flask import current_app

from ..db import get_db
from ..cohorts import non_seed
from ..queries import books
from ..report_queries import period_events, precedes, test_period_events
from .event_logging import EVENT_TYPES, utcnow
from .attribution import source_funnel

LABELS = {
    "light_participation": "가벼운 참여율", "text_participation": "한 줄 감상 참여율",
    "community_direct": "커뮤니티 직접 진입률 C/V", "others_exposure": "타인 감상 실제 노출률 E/V",
    "like_after_exposure": "노출 후 좋아요율 L/E", "reply_after_exposure": "노출 후 답글률 R/E",
    "interaction": "상호작용률 (L∪R)/E", "full_participation": "자유 감상 작성률",
    "community_without_short": "한 줄 미작성 직접 진입자", "community_after_short": "한 줄 작성 후 직접 진입자",
    "exposure_without_short": "한 줄 미작성 실제 노출자", "interaction_without_short": "상호작용 당시 한 줄 미작성자",
    "emoji_to_short": "이모지 → 한 줄 전환", "poll_to_short": "투표 → 한 줄 전환",
    "short_to_full": "한 줄 → 자유 감상 전환", "short_completion": "한 줄 작성 완료율", "full_completion": "자유 감상 작성 완료율",
}


def report():
    return _report(period_events(), current_counts)


def test_report():
    data = _report(test_period_events(), test_current_counts)
    for key in ("sample_met", "light_met", "text_met", "judgment"):
        data.pop(key)
    return data


def _report(all_events, counts):
    events = [e for e in all_events if e["in_period"]]
    book_ids = list(dict.fromkeys(b["id"] for b in books()))
    def had_short(event):
        return any(a["visitor_id"] == event["visitor_id"] and a["book_id"] == event["book_id"] and a["event_type"] == "short_review_submit" and precedes(a, event) for a in all_events)
    scopes = {}
    qualified = {}
    for bid in book_ids:
        selected = [e for e in events if e["book_id"] == bid]
        visitors = {e["visitor_id"] for e in selected if e["event_type"] == "book_view"}
        selected = [e for e in selected if e["visitor_id"] in visitors]
        sets = {name: {e["visitor_id"] for e in selected if e["event_type"] == name} for name in {e["event_type"] for e in selected}}
        exposures = [e for e in selected if e["event_type"] == "others_reveal"]
        likes, replies = set(), set()
        no_short_interaction = set()
        for e in selected:
            if e["event_type"] in ("like", "reply_submit") and any(x["visitor_id"] == e["visitor_id"] and precedes(x, e) for x in exposures):
                (likes if e["event_type"] == "like" else replies).add(e["visitor_id"])
                if not had_short(e):
                    no_short_interaction.add(e["visitor_id"])
        first_direct, first_exposure = {}, {}
        for e in selected:
            if e["event_type"] == "community_open":
                first_direct.setdefault(e["visitor_id"], e)
            if e["event_type"] == "others_reveal":
                first_exposure.setdefault(e["visitor_id"], e)
        extras = {
            "light_participation": sets.get("emoji_reaction", set()) | sets.get("poll_vote", set()),
            "text_participation": sets.get("short_review_submit", set()),
            "community_direct": sets.get("community_open", set()),
            "others_exposure": sets.get("others_reveal", set()),
            "like_after_exposure": likes, "reply_after_exposure": replies, "interaction": likes | replies,
            "full_participation": sets.get("full_review_submit", set()),
            "community_without_short": {v for v, e in first_direct.items() if not had_short(e)},
            "community_after_short": {v for v, e in first_direct.items() if had_short(e)},
            "exposure_without_short": {v for v, e in first_exposure.items() if not had_short(e)},
            "interaction_without_short": no_short_interaction,
        }
        for metric, first, second in (("emoji_to_short", "emoji_reaction", "short_review_submit"), ("poll_to_short", "poll_vote", "short_review_submit"), ("short_to_full", "short_review_submit", "full_review_submit"), ("short_completion", "short_review_start", "short_review_submit"), ("full_completion", "full_review_start", "full_review_submit")):
            extras[metric] = {e["visitor_id"] for e in selected if e["event_type"] == second and any(a["event_type"] == first and a["visitor_id"] == e["visitor_id"] and precedes(a, e) for a in selected)}
        qualified[bid] = (visitors, sets, extras, selected)
    qualified["all"] = (
        set().union(*(x[0] for x in qualified.values())),
        {name: set().union(*(x[1].get(name, set()) for x in qualified.values())) for name in {e["event_type"] for e in events}},
        {name: set().union(*(x[2][name] for x in qualified.values())) for name in LABELS},
        [e for x in qualified.values() for e in x[3]],
    )
    denominators = {"like_after_exposure": "others_exposure", "reply_after_exposure": "others_exposure", "interaction": "others_exposure", "emoji_to_short": "emoji_reaction", "poll_to_short": "poll_vote", "short_to_full": "short_review_submit", "short_completion": "short_review_start", "full_completion": "full_review_start"}
    no_rate = {"community_without_short", "community_after_short", "exposure_without_short", "interaction_without_short"}
    for scope, (visitors, sets, extras, selected) in qualified.items():
        metrics = []
        for name, label in LABELS.items():
            denominator = None if name in no_rate else len(extras.get(denominators[name], sets.get(denominators[name], set()))) if name in denominators else len(visitors)
            metrics.append({"metric_name": name, "label": label, "numerator": len(extras[name]), "denominator": denominator, "ratio": len(extras[name]) / denominator if denominator else None})
        event_counts = Counter(e["event_type"] for e in selected)
        event_rows = [{"name": name, "count": event_counts[name], "unique": len(sets.get(name, set())), "rate": len(sets.get(name, set())) / len(visitors) if visitors else None} for name in EVENT_TYPES if name not in ("landing_view", "book_select")]
        path_rows = [{"event": name, "source": source, "count": len(rows), "unique": len({e["visitor_id"] for e in rows})} for name in ("short_reviews_reveal", "others_reveal") for source in ("short_review_submit", "community_open", "community_restore", "return_visit") if (rows := [e for e in selected if e["event_type"] == name and e["reveal_source"] == source])]
        scopes[scope] = {"visitors": len(visitors), "metrics": metrics, "events": event_rows, "paths": path_rows, "current": counts(scope)}
    total = scopes["all"]
    light, text = total["metrics"][0]["ratio"], total["metrics"][1]["ratio"]
    sample = total["visitors"] >= 50
    reliable = current_app.config["DATA_RELIABLE"]
    judgment = "판정 불가" if not sample or not reliable else "검증" if light >= .3 and text >= .1 else "기각"
    raw = period_events(True)
    quality = {
        "submit_without_start": sum(not any(a["visitor_id"] == e["visitor_id"] and a["book_id"] == e["book_id"] and a["event_type"] == e["event_type"].replace("submit", "start") and precedes(a, e) for a in all_events) for e in events if e["event_type"] in ("short_review_submit", "full_review_submit", "reply_submit")),
        "interaction_without_confirmed_exposure": sum(not any(a["visitor_id"] == e["visitor_id"] and a["book_id"] == e["book_id"] and a["event_type"] == "others_reveal" and precedes(a, e) for a in events) for e in events if e["event_type"] in ("like", "reply_submit")),
        "client_order_arrival_mismatch": sum(a["timestamp"] < b["timestamp"] and a["client_sequence"] > b["client_sequence"] for i, a in enumerate(events) for b in events[i+1:] if a["page_view_id"] == b["page_view_id"]),
        "excluded_events": sum(e["is_test"] and e["in_period"] for e in raw),
    }
    landing = [e for e in events if e["event_type"] == "landing_view"]
    selects = [e for e in events if e["event_type"] == "book_select"]
    positions = []
    for bid in book_ids:
        for position in range(1, 4):
            relevant = [e for e in selects if e["book_id"] == bid and e["display_position"] == position]
            positions.append({"book_id": bid, "position": position, "display_count": sum(json.loads(e["displayed_book_order"])[position-1] == bid for e in landing), "select_count": len(relevant), "unique": len({e["visitor_id"] for e in relevant})})
    return {"generated_at": utcnow(), "start": current_app.config["EXPERIMENT_START"], "end": current_app.config["EXPERIMENT_END"], "timezone": current_app.config["DISPLAY_TIMEZONE"], "reliable": reliable, "quality_reason": current_app.config["DATA_QUALITY_REASON"], "sample_met": sample, "light_met": light is not None and light >= .3, "text_met": text is not None and text >= .1, "judgment": judgment, "scopes": scopes, "sources": source_funnel(events, qualified), "quality": quality, "landing": {"count": len(landing), "unique": len({e["visitor_id"] for e in landing})}, "selection": {"count": len(selects), "unique": len({e["visitor_id"] for e in selects}), "positions": positions, "arrivals": sum(bool(e["source_book_select_event_id"]) for e in events if e["event_type"] == "book_view"), "direct_arrivals": sum(not e["source_book_select_event_id"] for e in events if e["event_type"] == "book_view")}, "excluded": [dict(r) for r in get_db().execute("SELECT visitor_id,exclusion_reason FROM visitors WHERE is_test=1")], "contents": books()}


def current_counts(scope):
    db, result = get_db(), {}
    for key, table, alias, active, join in (
        ("emoji", "emoji_reactions", "x", "x.cancelled_at IS NULL", ""),
        ("poll", "poll_votes", "x", "x.cancelled_at IS NULL", ""),
        ("reviews", "reviews", "x", "x.deleted_at IS NULL", ""),
        ("likes", "likes", "x", "x.cancelled_at IS NULL AND r.deleted_at IS NULL AND owner.is_test=0", " JOIN reviews r ON x.review_id=r.review_id JOIN visitors owner ON owner.visitor_id=r.visitor_id"),
        ("replies", "replies", "x", "x.deleted_at IS NULL AND r.deleted_at IS NULL AND owner.is_test=0", " JOIN reviews r ON x.review_id=r.review_id JOIN visitors owner ON owner.visitor_id=r.visitor_id"),
    ):
        book_alias = "r" if join else "x"
        condition = f" AND {book_alias}.book_id=?" if scope != "all" else ""
        result[key] = db.execute(f"SELECT count(*) FROM {table} x JOIN visitors v ON x.visitor_id=v.visitor_id {join} WHERE v.is_test=0 AND {non_seed('v')} AND {active}{condition}", (scope,) if condition else ()).fetchone()[0]
    for kind in ("short", "full"):
        condition = " AND r.book_id=?" if scope != "all" else ""
        result[kind + "_reviews"] = db.execute("SELECT count(*) FROM reviews r JOIN visitors v ON r.visitor_id=v.visitor_id WHERE r.deleted_at IS NULL AND v.is_test=0 AND " + non_seed('v') + " AND r.review_type=?" + condition, (kind, scope) if condition else (kind,)).fetchone()[0]
    return result


def test_current_counts(scope):
    db, result = get_db(), {}
    for key, table, alias, active, join in (
        ("emoji", "emoji_reactions", "x", "x.cancelled_at IS NULL", ""),
        ("poll", "poll_votes", "x", "x.cancelled_at IS NULL", ""),
        ("reviews", "reviews", "x", "x.deleted_at IS NULL", ""),
        ("likes", "likes", "x", "x.cancelled_at IS NULL AND r.deleted_at IS NULL AND owner.is_test=1", " JOIN reviews r ON x.review_id=r.review_id JOIN visitors owner ON owner.visitor_id=r.visitor_id"),
        ("replies", "replies", "x", "x.deleted_at IS NULL AND r.deleted_at IS NULL AND owner.is_test=1", " JOIN reviews r ON x.review_id=r.review_id JOIN visitors owner ON owner.visitor_id=r.visitor_id"),
    ):
        book_alias = "r" if join else "x"
        condition = f" AND {book_alias}.book_id=?" if scope != "all" else ""
        result[key] = db.execute(f"SELECT count(*) FROM {table} x JOIN visitors v ON x.visitor_id=v.visitor_id {join} WHERE v.is_test=1 AND {non_seed('v')} AND {active}{condition}", (scope,) if condition else ()).fetchone()[0]
    for kind in ("short", "full"):
        condition = " AND r.book_id=?" if scope != "all" else ""
        result[kind + "_reviews"] = db.execute("SELECT count(*) FROM reviews r JOIN visitors v ON r.visitor_id=v.visitor_id WHERE r.deleted_at IS NULL AND v.is_test=1 AND " + non_seed('v') + " AND r.review_type=?" + condition, (kind, scope) if condition else (kind,)).fetchone()[0]
    return result


def csv_bytes(rows):
    rows = list(rows)
    output = io.StringIO(newline="")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        # Prefix all string cells, including harmless ones. Remove exactly one leading apostrophe to restore.
        writer.writerow({k: "'" + (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) if isinstance(v, (str, dict, list)) else v for k, v in row.items()})
    return output.getvalue().encode("utf-8-sig")


def export_zip():
    db = get_db()
    db.begin_read()
    try:
        summary = report()
        files = {"events.csv": csv_bytes(period_events(True))}
        for table in ("visitors", "emoji_reactions", "poll_votes", "reviews", "likes", "replies", "page_views"):
            columns = [name for name in db.columns(table) if name != "csrf_token"]
            files[table + ".csv"] = csv_bytes(dict(r) for r in db.execute(f"SELECT {','.join('x.' + c for c in columns)} FROM {table} x WHERE {non_seed('x')}"))
        files["visitor_sources.csv"] = csv_bytes(dict(r) for r in db.execute(
            "SELECT v.visitor_id,COALESCE(a.source,'direct') AS source FROM visitors v "
            "LEFT JOIN visitor_attributions a ON a.visitor_id=v.visitor_id "
            "WHERE v.is_test=0 AND " + non_seed('v')))
        files["source_funnel.csv"] = csv_bytes(
            dict(m, source=row["source"], landing_uv=row["landing"], book_view_uv=row["book_view"])
            for row in summary["sources"] for m in row["metrics"])
        metric_rows = []
        for scope, data in summary["scopes"].items():
            metric_rows.append({"scope": scope, "metric_name": "book_visitors", "unique_count": data["visitors"], "sample": data["visitors"], "judgment": summary["judgment"]})
            for metric in data["metrics"]:
                metric_rows.append(dict(metric, scope=scope, unique_count=metric["numerator"], sample=data["visitors"], judgment=summary["judgment"]))
            for e in data["events"]:
                metric_rows.append({"scope": scope, "metric_name": e["name"], "event_count": e["count"], "unique_count": e["unique"], "sample": data["visitors"], "judgment": summary["judgment"]})
            for kind, count in data["current"].items():
                metric_rows.append({"scope": scope, "metric_name": "current_" + kind, "current_count": count})
        metric_rows.extend([{"scope": "all", "metric_name": "landing_view", "event_count": summary["landing"]["count"], "unique_count": summary["landing"]["unique"]}, {"scope": "all", "metric_name": "book_select", "event_count": summary["selection"]["count"], "unique_count": summary["selection"]["unique"]}])
        files["metrics.csv"] = csv_bytes(metric_rows)
        files["conditions.csv"] = csv_bytes([{k: summary[k] for k in ("generated_at", "start", "end", "timezone", "reliable", "quality_reason")} | {"exclusion": "visitors.is_test=1: experiment metrics and production public content excluded; seed_participants: actor rows excluded from all experiment metrics and CSV, short/full content public", "interval": "start inclusive; end exclusive; UTC", "exposure_policy": current_app.config["EXPOSURE_POLICY"], "notice": current_app.config["NOTICE_TEXT"], "policy": "docs/requirements.md", "csv_restore": "Remove exactly one leading apostrophe from every string cell. Dates are UTC. Non-seed source events included; in_period marks interval. Normal actions targeting seed reviews remain; seed target review rows are not exported."}])
        files["contents.csv"] = csv_bytes(dict(r) for r in db.execute("SELECT * FROM book_contents"))
        files["paths.csv"] = csv_bytes(dict(path, scope=scope) for scope, data in summary["scopes"].items() for path in data["paths"])
        files["positions.csv"] = csv_bytes(summary["selection"]["positions"])
        files["quality.csv"] = csv_bytes([summary["quality"]])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        db.commit()
        return buffer.getvalue()
    except Exception:
        db.rollback()
        raise
