from __future__ import annotations

from collections import defaultdict

import pytz
from sqlalchemy import func

from app.extensions import db
from app.models import (
    Comment,
    CommissionMeeting,
    CommissionProject,
    DiscussionPoll,
    Suggestion,
    UserSeenItem,
)
from app.services.discussion_poll_service import (
    get_latest_poll_activity_by_discussion,
    get_poll_vote_summary,
    get_user_poll_votes,
)
from app.utils import get_local_now


_LOCAL_TZ = pytz.timezone("Europe/Madrid")
_UTC_TZ = pytz.UTC


def _to_local(dt):
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = _UTC_TZ.localize(dt)
    return dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)


def _to_utc(dt):
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = _LOCAL_TZ.localize(dt)
    return dt.astimezone(_UTC_TZ).replace(tzinfo=None)


def _normalize_seen_at(seen_at, latest_activity_at):
    if not seen_at or not latest_activity_at:
        return seen_at
    seen_utc = seen_at
    seen_local_to_utc = _to_utc(seen_at)
    if not seen_local_to_utc:
        return seen_at
    delta_local = abs((seen_local_to_utc - latest_activity_at).total_seconds())
    delta_utc = abs((seen_utc - latest_activity_at).total_seconds())
    return seen_local_to_utc if delta_local < delta_utc else seen_utc


def build_commission_cards(
    commissions,
    *,
    user_id: int | None,
    members_count_by_commission_id: dict[int, int] | None = None,
    max_commission_discussions: int = 4,
    max_commission_meetings: int = 4,
    max_projects: int = 3,
    max_project_discussions: int = 2,
    max_project_meetings: int = 2,
) -> dict[int, dict[str, object]]:
    commissions_list = [commission for commission in (commissions or []) if commission]
    if not commissions_list:
        return {}

    commission_ids = [commission.id for commission in commissions_list if getattr(commission, "id", None)]
    if not commission_ids:
        return {}

    members_count_by_commission_id = members_count_by_commission_id or {}
    now_dt = get_local_now()

    active_project_statuses = ("pendiente", "en_progreso")
    projects = (
        CommissionProject.query.filter(CommissionProject.commission_id.in_(commission_ids))
        .filter(CommissionProject.status.in_(active_project_statuses))
        .order_by(CommissionProject.created_at.desc())
        .all()
    )
    projects_by_commission: dict[int, list[CommissionProject]] = defaultdict(list)
    for project in projects:
        bucket = projects_by_commission[project.commission_id]
        if len(bucket) >= max_projects:
            continue
        bucket.append(project)

    selected_project_ids: set[int] = set()
    project_by_id: dict[int, CommissionProject] = {}
    for project_list in projects_by_commission.values():
        for project in project_list:
            selected_project_ids.add(project.id)
            project_by_id[project.id] = project

    active_project_ids = [project.id for project in projects]
    meetings_by_commission: dict[int, list[dict[str, object]]] = defaultdict(list)
    commission_meetings = (
        CommissionMeeting.query.filter(CommissionMeeting.commission_id.in_(commission_ids))
        .filter(CommissionMeeting.project_id.is_(None))
        .filter(CommissionMeeting.end_at >= now_dt)
        .order_by(CommissionMeeting.start_at.asc())
        .all()
    )
    for meeting in commission_meetings:
        bucket = meetings_by_commission[meeting.commission_id]
        if len(bucket) >= max_commission_meetings:
            continue
        bucket.append(
            {
                "title": meeting.title,
                "start_at": _to_local(meeting.start_at),
                "location": meeting.location,
            }
        )

    meetings_by_project: dict[int, list[dict[str, object]]] = defaultdict(list)
    if active_project_ids:
        project_meetings = (
            CommissionMeeting.query.filter(CommissionMeeting.project_id.in_(active_project_ids))
            .filter(CommissionMeeting.end_at >= now_dt)
            .order_by(CommissionMeeting.start_at.asc())
            .all()
        )
        for meeting in project_meetings:
            bucket = meetings_by_project[meeting.project_id]
            if len(bucket) >= max_project_meetings:
                continue
            bucket.append(
                {
                    "title": meeting.title,
                    "start_at": _to_local(meeting.start_at),
                    "location": meeting.location,
                }
            )

    commission_categories = [f"comision:{cid}" for cid in commission_ids]
    project_categories = [f"proyecto:{pid}" for pid in selected_project_ids]
    categories = commission_categories + project_categories

    discussions_by_commission: dict[int, list[Suggestion]] = defaultdict(list)
    discussions_by_project: dict[int, list[Suggestion]] = defaultdict(list)
    discussion_commission_by_id: dict[int, int] = {}
    discussion_ids: list[int] = []

    if categories:
        discussions = (
            Suggestion.query.filter(Suggestion.category.in_(categories))
            .filter(Suggestion.status.in_(("pendiente", "aprobada")))
            .order_by(Suggestion.updated_at.desc())
            .all()
        )
        for discussion in discussions:
            category = (discussion.category or "").strip()
            if category.startswith("comision:"):
                try:
                    commission_id = int(category.split(":", 1)[1])
                except (TypeError, ValueError):
                    continue
                if commission_id not in commission_ids:
                    continue
                bucket = discussions_by_commission[commission_id]
                if len(bucket) >= max_commission_discussions:
                    continue
                bucket.append(discussion)
                discussion_commission_by_id[discussion.id] = commission_id
                discussion_ids.append(discussion.id)
            elif category.startswith("proyecto:"):
                try:
                    project_id = int(category.split(":", 1)[1])
                except (TypeError, ValueError):
                    continue
                if project_id not in selected_project_ids:
                    continue
                bucket = discussions_by_project[project_id]
                if len(bucket) >= max_project_discussions:
                    continue
                bucket.append(discussion)
                project = project_by_id.get(project_id)
                if project:
                    discussion_commission_by_id[discussion.id] = project.commission_id
                discussion_ids.append(discussion.id)

    discussion_ids = list(dict.fromkeys(discussion_ids))
    seen_at_by_discussion_id: dict[int, object] = {}
    latest_comment_at_by_discussion_id: dict[int, object] = {}
    latest_poll_at_by_discussion_id: dict[int, object] = {}
    poll_by_discussion_id: dict[int, DiscussionPoll] = {}
    poll_info_by_discussion_id: dict[int, dict[str, object]] = {}

    if discussion_ids:
        seen_rows = (
            UserSeenItem.query.filter_by(user_id=user_id, item_type="suggestion")
            .filter(UserSeenItem.item_id.in_(discussion_ids))
            .all()
        )
        seen_at_by_discussion_id = {row.item_id: row.seen_at for row in seen_rows}

        latest_comment_rows = (
            db.session.query(Comment.suggestion_id, func.max(Comment.created_at))
            .filter(Comment.suggestion_id.in_(discussion_ids))
            .group_by(Comment.suggestion_id)
            .all()
        )
        latest_comment_at_by_discussion_id = {
            suggestion_id: latest_at for suggestion_id, latest_at in latest_comment_rows
        }
        latest_poll_at_by_discussion_id = get_latest_poll_activity_by_discussion(discussion_ids)

        active_polls = (
            DiscussionPoll.query.filter(DiscussionPoll.suggestion_id.in_(discussion_ids))
            .filter(DiscussionPoll.status == "activa", DiscussionPoll.end_at >= now_dt)
            .order_by(DiscussionPoll.created_at.desc())
            .all()
        )
        for poll in active_polls:
            if poll.suggestion_id not in poll_by_discussion_id:
                poll_by_discussion_id[poll.suggestion_id] = poll

        poll_ids = [poll.id for poll in poll_by_discussion_id.values()]
        poll_vote_summary = get_poll_vote_summary(poll_ids)
        user_votes = get_user_poll_votes(user_id, poll_ids)

        for discussion_id, poll in poll_by_discussion_id.items():
            summary = poll_vote_summary.get(poll.id, {})
            votes_total = sum(int(count) for count in summary.values())
            commission_id = discussion_commission_by_id.get(discussion_id)
            members_total = int(members_count_by_commission_id.get(commission_id, 0))
            poll_info_by_discussion_id[discussion_id] = {
                "id": poll.id,
                "title": poll.title,
                "end_at": _to_local(poll.end_at),
                "votes_total": votes_total,
                "members_total": members_total,
                "user_has_voted": poll.id in user_votes,
                "user_vote_value": user_votes.get(poll.id),
            }

    def build_discussion_info(discussion: Suggestion) -> dict[str, object]:
        discussion_id = discussion.id
        seen_at_raw = seen_at_by_discussion_id.get(discussion_id)
        latest_comment_at = latest_comment_at_by_discussion_id.get(discussion_id)
        latest_poll_at = latest_poll_at_by_discussion_id.get(discussion_id)
        latest_activity_at = latest_comment_at or latest_poll_at
        if latest_comment_at and latest_poll_at:
            latest_activity_at = max(latest_comment_at, latest_poll_at)
        # Normalize legacy seen_at stored in local time vs UTC.
        seen_at = _normalize_seen_at(seen_at_raw, latest_activity_at)

        is_unseen = False
        if not seen_at:
            is_unseen = True
        elif latest_comment_at and latest_comment_at > seen_at:
            is_unseen = True
        elif latest_poll_at and latest_poll_at > seen_at:
            is_unseen = True

        last_message_at = latest_comment_at or discussion.updated_at or discussion.created_at
        return {
            "id": discussion_id,
            "title": discussion.title,
            "last_message_at": _to_local(last_message_at),
            "seen": not is_unseen,
            "poll": poll_info_by_discussion_id.get(discussion_id),
        }

    cards_by_commission: dict[int, dict[str, object]] = {}
    for commission in commissions_list:
        commission_id = commission.id
        commission_discussions = [
            build_discussion_info(discussion)
            for discussion in discussions_by_commission.get(commission_id, [])
        ]
        project_cards = []
        for project in projects_by_commission.get(commission_id, []):
            project_discussions = [
                build_discussion_info(discussion)
                for discussion in discussions_by_project.get(project.id, [])
            ]
            project_cards.append({
                "id": project.id,
                "title": project.title,
                "discussions": project_discussions,
                "meetings": meetings_by_project.get(project.id, []),
            })
        cards_by_commission[commission_id] = {
            "discussions": commission_discussions,
            "meetings": meetings_by_commission.get(commission_id, []),
            "projects": project_cards,
        }

    return cards_by_commission
