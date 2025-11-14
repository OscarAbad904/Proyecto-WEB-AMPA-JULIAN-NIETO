import os

from app import create_app, db
from app.models import Role, User

app = create_app(os.getenv("FLASK_ENV", "development"))

@app.cli.command("create-admin")
def create_admin():
    """Create a default admin user using env credentials."""
    email = os.getenv("ADMIN_EMAIL", "admin@ampa-jnt.es")
    username = "admin"
    password = os.getenv("ADMIN_PASSWORD", "changeme")
    if User.query.filter_by(email=email).first():
        print("Admin already exists")
        return
    admin_role = Role.query.filter_by(name="admin").first()
    if not admin_role:
        admin_role = Role(name="admin")
        db.session.add(admin_role)
        db.session.commit()
    admin = User(username=username, email=email, is_active=True, email_verified=True, role=admin_role)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    print(f"Created admin user {email}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
