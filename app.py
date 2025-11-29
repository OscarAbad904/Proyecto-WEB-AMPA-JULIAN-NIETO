import os

from Api_AMPA_WEB import create_app, db, Role, User, make_lookup_hash

app = create_app(os.getenv("FLASK_ENV", "development"))

@app.cli.command("create-admin")
def create_admin():
    """Create a default admin user."""
    email = "admin@ampa-jnt.es"
    username = "admin"
    password = "changeme"
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

@app.cli.command("setup-drive-folders")
def setup_drive_folders():
    """Setup Google Drive folders for Eventos, Documentos, and Noticias.
    
    This command creates the folders in Google Drive (if they don't exist)
    and prints their IDs so you can add them to your .env file.
    """
    from media_utils import ensure_folder
    
    with app.app_context():
        folders = {
            "GOOGLE_DRIVE_NEWS_FOLDER_ID": app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_NAME", "Noticias"),
            "GOOGLE_DRIVE_EVENTS_FOLDER_ID": app.config.get("GOOGLE_DRIVE_EVENTS_FOLDER_NAME", "Eventos"),
            "GOOGLE_DRIVE_DOCS_FOLDER_ID": app.config.get("GOOGLE_DRIVE_DOCS_FOLDER_NAME", "Documentos"),
        }
        
        shared_drive_id = app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        print("\n📁 Setting up Google Drive folders...\n")
        
        for env_var, folder_name in folders.items():
            try:
                folder_id = ensure_folder(folder_name, parent_id=None, drive_id=shared_drive_id)
                print(f"✅ {folder_name}: {folder_id}")
                print(f"   Add to .env: {env_var}={folder_id}\n")
            except Exception as e:
                print(f"❌ Error creating {folder_name}: {e}\n")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
