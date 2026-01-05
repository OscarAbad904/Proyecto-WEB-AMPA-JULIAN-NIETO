from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import func
from flask import url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (
    Commission,
    CommissionMembership,
    CommissionProject,
    DiscussionPoll,
    DiscussionPollVote,
    Suggestion,
    User,
)


@dataclass(frozen=True)
class DiscussionScope:
    commission: Commission | None
    project: CommissionProject | None


def _parse_discussion_category(raw_category: str | None) -> tuple[str | None, int | None]:
    category = (raw_category or "").strip().lower()
    if category.startswith("comision:"):
        try:
            return "commission", int(category.split(":", 1)[1])
        except (TypeError, ValueError):
            return None, None
    if category.startswith("proyecto:"):
        try:
            return "project", int(category.split(":", 1)[1])
        except (TypeError, ValueError):
            return None, None
    return None, None


def resolve_discussion_scope(suggestion: Suggestion | None) -> DiscussionScope:
    if not suggestion:
        return DiscussionScope(commission=None, project=None)
    scope_type, scope_id = _parse_discussion_category(getattr(suggestion, "category", None))
    if scope_type == "commission" and scope_id:
        return DiscussionScope(commission=Commission.query.get(scope_id), project=None)
    if scope_type == "project" and scope_id:
        project = CommissionProject.query.get(scope_id)
        commission = Commission.query.get(project.commission_id) if project else None
        return DiscussionScope(commission=commission, project=project)
    return DiscussionScope(commission=None, project=None)


def get_active_commission_members(commission_id: int) -> list[CommissionMembership]:
    if not commission_id:
        return []
    return (
        CommissionMembership.query.options(joinedload(CommissionMembership.user))
        .join(User)
        .filter(
            CommissionMembership.commission_id == commission_id,
            CommissionMembership.is_active.is_(True),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .all()
    )


def get_poll_vote_summary(poll_ids: Iterable[int]) -> dict[int, dict[int, int]]:
    poll_ids_list = [int(pid) for pid in poll_ids if pid]
    if not poll_ids_list:
        return {}
    rows = (
        db.session.query(
            DiscussionPollVote.poll_id,
            DiscussionPollVote.value,
            func.count(DiscussionPollVote.id),
        )
        .filter(DiscussionPollVote.poll_id.in_(poll_ids_list))
        .group_by(DiscussionPollVote.poll_id, DiscussionPollVote.value)
        .all()
    )
    summary: dict[int, dict[int, int]] = {}
    for poll_id, value, count in rows:
        summary.setdefault(int(poll_id), {})[int(value)] = int(count)
    return summary


def get_user_poll_votes(user_id: int | None, poll_ids: Iterable[int]) -> dict[int, int]:
    if not user_id:
        return {}
    poll_ids_list = [int(pid) for pid in poll_ids if pid]
    if not poll_ids_list:
        return {}
    rows = (
        DiscussionPollVote.query.with_entities(DiscussionPollVote.poll_id, DiscussionPollVote.value)
        .filter(DiscussionPollVote.user_id == int(user_id))
        .filter(DiscussionPollVote.poll_id.in_(poll_ids_list))
        .all()
    )
    return {int(poll_id): int(value) for poll_id, value in rows}


def get_latest_poll_activity_by_discussion(discussion_ids: Iterable[int]) -> dict[int, object]:
    discussion_ids_list = [int(did) for did in discussion_ids if did]
    if not discussion_ids_list:
        return {}
    rows = (
        db.session.query(
            DiscussionPoll.suggestion_id,
            func.max(DiscussionPoll.created_at),
            func.max(DiscussionPoll.closed_at),
            func.max(DiscussionPoll.nulled_at),
        )
        .filter(DiscussionPoll.suggestion_id.in_(discussion_ids_list))
        .group_by(DiscussionPoll.suggestion_id)
        .all()
    )
    latest_by_discussion: dict[int, object] = {}
    for suggestion_id, max_created, max_closed, max_nulled in rows:
        candidates = [dt for dt in (max_created, max_closed, max_nulled) if dt]
        latest_by_discussion[int(suggestion_id)] = max(candidates) if candidates else None
    return latest_by_discussion


def build_discussion_poll_url(
    *,
    suggestion: Suggestion,
    poll_id: int,
    commission: Commission | None = None,
    project: CommissionProject | None = None,
) -> str:
    return_to = None
    if commission and project:
        return_to = url_for(
            "members.commission_project_detail",
            slug=commission.slug,
            project_id=project.id,
        )
    elif commission:
        return_to = url_for("members.commission_detail", slug=commission.slug)

    poll_url = url_for(
        "members.detalle_sugerencia",
        suggestion_id=suggestion.id,
        poll=poll_id,
        return_to=return_to,
        _external=True,
    )
    return f"{poll_url}#poll-{poll_id}"
