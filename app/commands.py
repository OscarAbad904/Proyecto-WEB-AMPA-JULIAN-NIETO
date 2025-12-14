import click
from flask import Flask
from app.extensions import db
from app.models import Role, User
from app.utils import normalize_lookup

def register_commands(app: Flask):
    @app.cli.command("create-admin")
    def create_admin():
        """Create a default admin user."""
        email = "admin@ampa-jnt.es"
        username = "admin"
        password = "changeme"
        if User.query.filter_by(email=email).first():
            print("Admin already exists")
            return
        admin_role = Role.query.filter_by(name_lookup=normalize_lookup("admin")).first()
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
        from app.media_utils import ensure_folder

        shared_drive_id = app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        root_folder_name = (app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_NAME") or "WEB Ampa").strip()

        print("\n📁 Setting up Google Drive folders...\n")

        try:
            root_folder_id = ensure_folder(root_folder_name, parent_id=None, drive_id=shared_drive_id)
            print(f"✅ {root_folder_name}: {root_folder_id}")
            print(f"   Add to .env: GOOGLE_DRIVE_ROOT_FOLDER_ID={root_folder_id}\n")
        except Exception as e:
            root_folder_id = None
            print(f"❌ Error creating root folder {root_folder_name}: {e}\n")

        folders = {
            "GOOGLE_DRIVE_NEWS_FOLDER_ID": app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_NAME", "Noticias"),
            "GOOGLE_DRIVE_EVENTS_FOLDER_ID": app.config.get("GOOGLE_DRIVE_EVENTS_FOLDER_NAME", "Eventos"),
            "GOOGLE_DRIVE_DOCS_FOLDER_ID": app.config.get("GOOGLE_DRIVE_DOCS_FOLDER_NAME", "Documentos"),
        }

        for env_var, folder_name in folders.items():
            try:
                folder_id = ensure_folder(folder_name, parent_id=root_folder_id, drive_id=shared_drive_id)
                print(f"✅ {folder_name}: {folder_id}")
                print(f"   Add to .env: {env_var}={folder_id}\n")
            except Exception as e:
                print(f"❌ Error creating {folder_name}: {e}\n")

    @app.cli.command("regenerate-google-token")
    def regenerate_google_token():
        """Regenerate OAuth token with Calendar scope.
        
        This command must be run ONCE locally to generate a token that includes
        both Drive and Calendar permissions. After regeneration, upload the
        resulting token_drive.json to Render as an environment variable.
        
        IMPORTANT: This will open a browser for Google OAuth authorization.
        """
        from app.services.calendar_service import regenerate_token_with_calendar_scope
        
        print("\n🔐 Regenerando token OAuth con permisos de Calendar...\n")
        print("⚠️  IMPORTANTE: Esto abrirá el navegador para autorización de Google.")
        print("   Asegúrate de autorizar TODOS los permisos solicitados.\n")
        
        result = regenerate_token_with_calendar_scope()
        
        if result.get("ok"):
            print(f"✅ {result['message']}")
            print(f"\n📁 Token guardado en: {result.get('token_path')}")
            print(f"   Scopes incluidos: {result.get('scopes')}")
            print("\n📋 Próximos pasos:")
            print("   1. Lee el contenido de token_drive.json")
            print("   2. Encríptalo con tu clave Fernet")
            print("   3. Súbelo a Render como GOOGLE_DRIVE_TOKEN_JSON")
        else:
            print(f"❌ Error: {result['message']}")

    @app.cli.command("backup-db-to-drive")
    @click.option("--force", is_flag=True, help="Ejecuta aunque DB_BACKUP_ENABLED=false.")
    def backup_db_to_drive(force: bool):
        """Create a database backup and upload it to Google Drive."""
        from app.services.db_backup_service import run_db_backup_to_drive

        with app.app_context():
            result = run_db_backup_to_drive(force=force)

        if result.ok:
            print(f"OK: {result.message}")
            if result.drive_folder_id:
                print(f"Drive folder: {result.drive_folder_id}")
            if result.drive_file_id:
                print(f"Drive file: {result.drive_file_id}")
        else:
            raise SystemExit(f"ERROR: {result.message}")

    @app.cli.command("test-calendar")
    def test_calendar():
        """Test Google Calendar connection and fetch events.
        
        This command tests the Calendar API connection and displays
        upcoming events to verify the configuration is working.
        """
        from app.services.calendar_service import get_calendar_events
        
        print("\n📅 Probando conexión con Google Calendar...\n")
        
        result = get_calendar_events(max_results=10, use_cache=False)
        
        if result.get("ok"):
            print(f"✅ Conexión exitosa!")
            print(f"   Calendario: {result.get('calendar_name', 'N/A')}")
            print(f"   Eventos encontrados: {result['total']}")
            print(f"   Desde cache: {'Sí' if result.get('cached') else 'No'}")
            
            if result['eventos']:
                print("\n📋 Próximos eventos:")
                for i, evento in enumerate(result['eventos'][:5], 1):
                    fecha = evento['inicio'][:10] if evento['inicio'] else 'Sin fecha'
                    print(f"   {i}. [{fecha}] {evento['titulo']}")
            else:
                print("\n   No hay eventos próximos.")
        else:
            print(f"❌ Error: {result.get('error')}")
            print("\n💡 Posibles soluciones:")
            print("   1. Ejecuta 'flask regenerate-google-token' para regenerar el token")
            print("   2. Verifica que GOOGLE_CALENDAR_ID esté configurado correctamente")
            print("   3. Comprueba que el calendario tenga eventos públicos o compartidos")
