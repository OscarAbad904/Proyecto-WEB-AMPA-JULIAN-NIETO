from __future__ import annotations

import os
import threading
import time

from flask import Flask

from app.extensions import db
from app.models import DiscussionPoll
from app.services.discussion_poll_service import (
    build_discussion_poll_url,
    get_active_commission_members,
    get_poll_vote_summary,
    resolve_discussion_scope,
)
from app.services.mail_service import send_discussion_poll_result
from app.utils import get_local_now

_poll_thread: threading.Thread | None = None
_poll_lock = threading.Lock()


def _close_due_polls(app: Flask) -> None:
    now_dt = get_local_now()
    due_polls = (
        DiscussionPoll.query.filter(DiscussionPoll.status == "activa")
        .filter(DiscussionPoll.end_at <= now_dt)
        .all()
    )
    if not due_polls:
        return

    closed_ids: list[int] = []
    for poll in due_polls:
        updated = (
            DiscussionPoll.query.filter_by(id=poll.id, status="activa")
            .update({"status": "finalizada", "closed_at": now_dt}, synchronize_session=False)
        )
        if updated:
            closed_ids.append(int(poll.id))
            if poll.suggestion:
                poll.suggestion.updated_at = now_dt

    if closed_ids:
        db.session.commit()

    polls_to_notify = (
        DiscussionPoll.query.filter(DiscussionPoll.id.in_(closed_ids))
        .filter(DiscussionPoll.notify_enabled.is_(True))
        .filter(DiscussionPoll.result_notified_at.is_(None))
        .all()
    )
    if not polls_to_notify:
        return

    for poll in polls_to_notify:
        updated = (
            DiscussionPoll.query.filter_by(id=poll.id, result_notified_at=None)
            .update({"result_notified_at": now_dt}, synchronize_session=False)
        )
        if not updated:
            continue
        db.session.commit()

        suggestion = poll.suggestion
        scope = resolve_discussion_scope(suggestion)
        commission = scope.commission
        if not commission:
            continue

        members = get_active_commission_members(commission.id)
        member_count = len(members)

        summary = get_poll_vote_summary([poll.id]).get(int(poll.id), {})
        votes_for = int(summary.get(1, 0))
        votes_against = int(summary.get(-1, 0))
        abstentions = max(member_count - (votes_for + votes_against), 0)

        poll_url = build_discussion_poll_url(
            suggestion=suggestion,
            poll_id=poll.id,
            commission=commission,
            project=scope.project,
        )

        for membership in members:
            user = membership.user
            if not user or not user.email:
                continue
            try:
                result = send_discussion_poll_result(
                    poll=poll,
                    suggestion=suggestion,
                    commission=commission,
                    project=scope.project,
                    recipient_email=user.email,
                    app_config=app.config,
                    poll_url=poll_url,
                    votes_for=votes_for,
                    votes_against=votes_against,
                    abstentions=abstentions,
                )
                if not result.get("ok"):
                    app.logger.warning(
                        "Fallo enviando resultado de votacion %s a %s: %s",
                        poll.id,
                        user.email,
                        result.get("error"),
                    )
            except Exception as exc:  # noqa: BLE001
                app.logger.exception(
                    "Error enviando resultado de votacion %s a %s: %s",
                    poll.id,
                    user.email,
                    exc,
                )


def start_discussion_poll_scheduler(app: Flask) -> None:
    if os.getenv("AMPA_DISABLE_BACKGROUND_JOBS") in {"1", "true", "yes"}:
        return

    if (app.debug or app.config.get("DEBUG")) and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return

    if os.getenv("FLASK_RUN_FROM_CLI") == "true":
        return

    interval = int(app.config.get("DISCUSSION_POLL_CLOSE_INTERVAL", 60))
    interval = max(15, interval)

    global _poll_thread
    with _poll_lock:
        if _poll_thread and _poll_thread.is_alive():
            return

        def _loop() -> None:
            time.sleep(30)
            while True:
                try:
                    with app.app_context():
                        db.engine.dispose()
                        _close_due_polls(app)
                        db.session.remove()
                except Exception as exc:  # noqa: BLE001
                    app.logger.exception("Error en scheduler de votaciones: %s", exc)
                time.sleep(interval)

        _poll_thread = threading.Thread(target=_loop, name="discussion-poll-scheduler", daemon=True)
        _poll_thread.start()
