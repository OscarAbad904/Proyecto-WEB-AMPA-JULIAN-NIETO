from app.models import Role, User
from app.extensions import db


def test_user_password_hashing(app):
    with app.app_context():
        role = Role(name="socio")
        db.session.add(role)
        db.session.commit()
        user = User(username="testuser", email="test@example.com", role=role)
        user.set_password("strongpassword")
        assert user.password_hash != "strongpassword"
        assert user.check_password("strongpassword")
        assert not user.check_password("wrong")
