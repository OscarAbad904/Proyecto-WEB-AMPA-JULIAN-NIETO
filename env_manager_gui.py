import os
import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from dotenv import dotenv_values

# -------------------------------------------------------------------
# IMPORTACIONES DE TU APP (Mantenidas igual)
# -------------------------------------------------------------------
from Api_AMPA_WEB import create_app, db, User, Role, make_lookup_hash
from config import encrypt_value, decrypt_env_var, decrypt_value, ensure_google_drive_credentials_file, ensure_google_drive_token_file

ENV_PATH = ".env"
CONFIG_FILE = "gui_config.json"  # Archivo para guardar preferencias (último usuario)

SENSITIVE_KEYS = {
    "SECRET_KEY",
    "SECURITY_PASSWORD_SALT",
    "MAIL_PASSWORD",
    "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON",
    "GOOGLE_DRIVE_TOKEN_JSON",
}

# -------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -------------------------------------------------------------------

def load_env():
    return dotenv_values(ENV_PATH)

def save_env(env_dict):
    lines = []
    for key, value in env_dict.items():
        if value is None:
            continue
        lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def _get_admin_user():
    return User.query.join(Role).filter(Role.name_lookup == make_lookup_hash("admin")).first()

def verify_or_create_admin(app, email, password):
    with app.app_context():
        admin = _get_admin_user()
        if admin:
            if admin.email != email:
                return False, "El administrador registrado usa otro correo.", None
            if not admin.check_password(password):
                return False, "Contraseña incorrecta.", None
            return True, "Autenticado.", admin

        role = Role.query.filter_by(name_lookup=make_lookup_hash("admin")).first()
        if not role:
            role = Role(name="admin")
            db.session.add(role)
            db.session.commit()
        admin = User(username="admin", email=email, is_active=True, email_verified=True, role=role)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return True, "Administrador creado.", admin

def update_admin_password(app, email, new_password):
    with app.app_context():
        admin = _get_admin_user()
        if not admin or admin.email != email:
            return False
        admin.set_password(new_password)
        db.session.commit()
        return True

# -------------------------------------------------------------------
# CLASE PRINCIPAL DE LA INTERFAZ
# -------------------------------------------------------------------

class EnvManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # Configuración de ventana
        self.title("Gestor de Configuración AMPA (Seguro)")
        self.geometry("700x700")
        self.minsize(550, 550)
        self.center_window()
        
        # Estilos visuales
        style = ttk.Style()
        style.theme_use('clam') # 'clam' suele verse mejor que 'default' en windows/linux
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("Card.TFrame", background="#f0f0f0", relief="groove")
        
        self.env = load_env()
        self.unlocked = False
        self.auth_email = None
        self.auth_password = None
        self.password_visibility = {}  # Rastrear visibilidad de contraseñas

        self.fields = [
            "SECRET_KEY",
            "SECURITY_PASSWORD_SALT",
            "MAIL_SERVER",
            "MAIL_PORT",
            "MAIL_USE_TLS",
            "MAIL_USERNAME",
            "MAIL_PASSWORD",
            "MAIL_DEFAULT_SENDER",
            "SQLALCHEMY_DATABASE_URI",
            "GOOGLE_DRIVE_NEWS_FOLDER_ID",
            "GOOGLE_DRIVE_NEWS_FOLDER_NAME",
            "GOOGLE_DRIVE_EVENTS_FOLDER_ID",
            "GOOGLE_DRIVE_EVENTS_FOLDER_NAME",
            "GOOGLE_DRIVE_DOCS_FOLDER_ID",
            "GOOGLE_DRIVE_DOCS_FOLDER_NAME",
            "GOOGLE_DRIVE_SHARED_DRIVE_ID",
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE",
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON",
            "GOOGLE_DRIVE_TOKEN_JSON",
            "NEWS_IMAGE_FORMAT",
            "NEWS_IMAGE_QUALITY",
        ]

        self.entries = {}
        
        # Contenedor principal
        self.main_container = ttk.Frame(self)
        self.main_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Iniciar UI
        self.setup_login_ui()
        self.setup_config_ui()
        
        # Mostrar Login primero
        self.show_login()

    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

    # --- Lógica de "Recordar Usuario" ---
    def load_last_user(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("last_email", "")
            except:
                return ""
        return ""

    def save_last_user(self, email):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"last_email": email}, f)
        except Exception as e:
            print(f"No se pudo guardar preferencia: {e}")

    # --- UI de Login ---
    def setup_login_ui(self):
        self.login_frame = ttk.Frame(self.main_container)
        
        # Tarjeta central para login
        card = ttk.Frame(self.login_frame, style="Card.TFrame", padding=30)
        card.place(relx=0.5, rely=0.4, anchor="center")

        ttk.Label(card, text="Acceso Administrativo", style="Header.TLabel").pack(pady=(0, 20))
        
        # Campo Email
        ttk.Label(card, text="Correo Electrónico:").pack(anchor="w")
        self.login_email = ttk.Entry(card, width=40)
        self.login_email.pack(pady=(5, 15))
        
        # Cargar último usuario
        last_user = self.load_last_user()
        if last_user:
            self.login_email.insert(0, last_user)
        
        # Campo Password
        ttk.Label(card, text="Contraseña:").pack(anchor="w")
        self.login_password = ttk.Entry(card, width=40, show="•")
        self.login_password.pack(pady=(5, 20))
        
        # Botón
        btn = ttk.Button(card, text="Iniciar Sesión", command=self.handle_auth)
        btn.pack(fill="x")
        
        # Bind Enter key
        self.bind('<Return>', lambda event: self.handle_auth())

    # --- UI de Configuración (Scrollable) ---
    def setup_config_ui(self):
        self.config_container = ttk.Frame(self.main_container)
        
        # Barra superior
        top_bar = ttk.Frame(self.config_container)
        top_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(top_bar, text="Editar Variables de Entorno", style="Header.TLabel").pack(side="left")
        ttk.Button(top_bar, text="Cambiar Password Admin", command=self.update_admin).pack(side="right")

        # Área Scrollable
        canvas = tk.Canvas(self.config_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.config_container, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        # Crear ventana dentro del canvas
        canvas_window = canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # Ajustar ancho del frame al ancho del canvas
        def configure_canvas(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", configure_canvas)

        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Layout del scroll
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Generar campos dinámicamente
        for idx, key in enumerate(self.fields):
            row_frame = ttk.Frame(self.scrollable_frame, padding=(5, 5))
            row_frame.pack(fill="x", pady=2)
            
            lbl = ttk.Label(row_frame, text=key, width=35, anchor="w")
            lbl.pack(side="left")
            
            # Si es sensitivo, indicarlo visualmente (opcional)
            if key in SENSITIVE_KEYS:
                lbl.configure(foreground="#d9534f") # Rojo suave

            entry = ttk.Entry(row_frame)
            entry.pack(side="left", fill="x", expand=True, padx=5)
            self.entries[key] = entry
            
            # Si es sensible, agregar botón de visibilidad
            if key in SENSITIVE_KEYS:
                self.password_visibility[key] = False  # Iniciar oculto
                btn = ttk.Button(
                    row_frame, 
                    text="👁", 
                    width=3,
                    command=lambda k=key: self.toggle_password_visibility(k)
                )
                btn.pack(side="left", padx=2)

        # Botón Guardar inferior
        bottom_bar = ttk.Frame(self.config_container, padding=10)
        bottom_bar.pack(fill="x")
        save_btn = ttk.Button(bottom_bar, text="GUARDAR CAMBIOS (.ENV)", command=self.save_encrypted)
        save_btn.pack(fill="x", ipady=5)

    def show_login(self):
        self.config_container.pack_forget()
        self.login_frame.pack(fill="both", expand=True)

    def show_config(self):
        self.login_frame.pack_forget()
        self.config_container.pack(fill="both", expand=True)
        self.unbind('<Return>') # Quitar bind del enter

    # --- Lógica de Negocio ---

    def handle_auth(self):
        email = self.login_email.get().strip()
        password = self.login_password.get()
        if not email or not password:
            messagebox.showerror("Faltan datos", "Introduce correo y contraseña.")
            return
        
        try:
            app = create_app(os.getenv("FLASK_ENV", "development"))
            ok, msg, _ = verify_or_create_admin(app, email, password)
        except Exception as e:
            messagebox.showerror("Error de Conexión", f"No se pudo conectar a la DB:\n{e}")
            return

        if not ok:
            messagebox.showerror("Acceso denegado", msg)
            return
        
        # Login correcto
        self.save_last_user(email) # Guardar preferencia
        self.auth_email = email
        self.auth_password = password
        self.populate_entries()
        self.unlocked = True
        
        messagebox.showinfo("Bienvenido", f"{msg}\nModo edición habilitado.")
        self.show_config()

    def populate_entries(self):
        # Limpiar y rellenar
        for key, entry in self.entries.items():
            entry.delete(0, tk.END)
            val = self.env.get(key, "")
            
            # Si es sensible, desencriptar para mostrar
            if key in SENSITIVE_KEYS and val:
                try:
                    val = decrypt_value(val)
                except Exception as e:
                    print(f"No se pudo desencriptar {key}: {e}")
                    val = "[ERROR descifrado]"
                
                # Mostrar como oculto por defecto
                entry.config(show="•")
            
            entry.insert(0, val)

    def toggle_password_visibility(self, key: str):
        """Alterna la visibilidad de una contraseña entre oculta y visible."""
        if key not in self.entries:
            return
        
        entry = self.entries[key]
        is_visible = self.password_visibility.get(key, False)
        
        # Alternar visibilidad
        self.password_visibility[key] = not is_visible
        
        # Cambiar el atributo 'show' del Entry
        if self.password_visibility[key]:
            # Mostrar texto plano
            entry.config(show="")
        else:
            # Ocultar con asteriscos
            entry.config(show="•")

    def save_encrypted(self):
        if not self.unlocked:
            return
        
        updated = {}
        # Leer campos del formulario
        for key, entry in self.entries.items():
            plain = entry.get().strip()
            
            # Si el campo está vacío, lo dejamos vacío
            if not plain:
                updated[key] = ""
                continue
                
            # Lógica de encriptación
            if key in SENSITIVE_KEYS:
                # Comprobar si ya estaba encriptado (si empieza por el prefijo de tu config, etc)
                # O simplemente re-encriptar siempre lo que hay en el input:
                try:
                    # Asumimos que lo que hay en el Entry es TEXTO PLANO que el usuario quiere guardar
                    updated[key] = encrypt_value(plain)
                except Exception as e:
                    messagebox.showerror("Error", f"Fallo al encriptar {key}: {e}")
                    return
            else:
                updated[key] = plain
        
        try:
            save_env(updated)
            # Actualizar memoria
            self.env = updated
            
            # Si se guardaron variables de Google Drive, crear los archivos desencriptados
            files_created = []
            errors = []
            
            if "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON" in updated and updated["GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON"]:
                try:
                    ensure_google_drive_credentials_file(os.getcwd())
                    files_created.append("credentials_drive_oauth.json")
                except Exception as e:
                    errors.append(f"credentials_drive_oauth.json: {e}")
            
            if "GOOGLE_DRIVE_TOKEN_JSON" in updated and updated["GOOGLE_DRIVE_TOKEN_JSON"]:
                try:
                    ensure_google_drive_token_file(os.getcwd())
                    files_created.append("token_drive.json")
                except Exception as e:
                    errors.append(f"token_drive.json: {e}")
            
            if errors:
                msg = f"Archivo .env guardado.\nArchivos creados: {', '.join(files_created) if files_created else 'ninguno'}\nErrores: {'; '.join(errors)}"
                messagebox.showwarning("Advertencia", msg)
            elif files_created:
                msg = f"Archivo .env actualizado y cifrado correctamente.\nArchivos creados: {', '.join(files_created)}"
                messagebox.showinfo("Éxito", msg)
            else:
                messagebox.showinfo("Éxito", "Archivo .env actualizado y cifrado correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo escribir el archivo: {e}")

    def update_admin(self):
        new_password = simpledialog.askstring(
            "Cambiar Contraseña",
            f"Nueva contraseña para {self.auth_email}:",
            show="•",
            parent=self,
        )
        if not new_password:
            return
            
        app = create_app(os.getenv("FLASK_ENV", "development"))
        if update_admin_password(app, self.auth_email, new_password):
            self.auth_password = new_password
            self.env["ADMIN_PASSWORD"] = encrypt_value(new_password)
            save_env(self.env) # Guardar inmediatamente el cambio de pass en env
            messagebox.showinfo("Actualizado", "Contraseña de administrador actualizada en DB y .env")
        else:
            messagebox.showerror("Error", "No se pudo actualizar la contraseña en la base de datos.")

if __name__ == "__main__":
    app = EnvManagerApp()
    app.mainloop()
