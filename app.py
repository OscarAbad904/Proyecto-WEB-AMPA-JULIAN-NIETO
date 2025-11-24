import os

from Api_AMPA_WEB import create_app, db, Role, User, make_lookup_hash
from config import decrypt_env_var

app = create_app(os.getenv("FLASK_ENV", "development"))

@app.cli.command("create-admin")
def create_admin():
    """Create a default admin user using env credentials."""
    email = decrypt_env_var("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL", "admin@ampa-jnt.es")
    username = "admin"
    password = decrypt_env_var("ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD", "changeme")
    if User.query.filter_by(email=email).first():
        print("Admin already exists")
        return
    admin_role = Role.query.filter_by(name_lookup=make_lookup_hash("admin")).first()
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
