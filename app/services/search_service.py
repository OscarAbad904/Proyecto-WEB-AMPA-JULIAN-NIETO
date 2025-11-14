from sqlalchemy import or_

from ..models import Event, Post
from ..extensions import db


class SearchService:
    @staticmethod
    def search_posts(term: str, limit: int = 10):
        statement = (
            db.select(Post)
            .filter(
                or_(
                    Post.title.ilike(f"%{term}%"),
                    Post.body_html.ilike(f"%{term}%"),
                )
            )
            .limit(limit)
        )
        return db.session.scalars(statement).all()

    @staticmethod
    def search_events(term: str, limit: int = 10):
        statement = (
            db.select(Event)
            .filter(
                or_(
                    Event.title.ilike(f"%{term}%"),
                    Event.description_html.ilike(f"%{term}%"),
                )
            )
            .limit(limit)
        )
        return db.session.scalars(statement).all()
