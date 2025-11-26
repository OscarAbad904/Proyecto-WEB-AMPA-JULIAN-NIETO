import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from dotenv import dotenv_values

# Importamos la app para acceder a db/User y create_app
from Api_AMPA_WEB import create_app, db, User, Role, make_lookup_hash
from config import encrypt_value, decrypt_env_var


ENV_PATH = ".env"


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
                return False, "El administrador registrado usa otro correo."
            if not admin.check_password(password):
                return False, "Contraseña incorrecta para el administrador."
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


class EnvManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gestor .env cifrado AMPA")
        self.resizable(False, False)
        self.env = load_env()
        self.unlocked = False
        self.auth_email = None
        self.auth_password = None

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
            "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE",
            "GOOGLE_DRIVE_NEWS_FOLDER_ID",
            "GOOGLE_DRIVE_NEWS_FOLDER_NAME",
            "GOOGLE_DRIVE_SHARED_DRIVE_ID",
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE",
            "NEWS_IMAGE_FORMAT",
            "NEWS_IMAGE_QUALITY",
        ]

        # Frame de autenticación
        self.login_frame = ttk.Frame(self, padding=10)
        ttk.Label(self.login_frame, text="Correo administrador").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(self.login_frame, text="Contraseña").grid(row=1, column=0, sticky="w", pady=4)
        self.login_email = ttk.Entry(self.login_frame, width=50)
        self.login_email.grid(row=0, column=1, pady=4)
        self.login_password = ttk.Entry(self.login_frame, width=50, show="*")
        self.login_password.grid(row=1, column=1, pady=4)
        ttk.Button(self.login_frame, text="Acceder", command=self.handle_auth).grid(row=2, column=0, columnspan=2, pady=8)
        self.login_frame.grid(row=0, column=0, sticky="nsew")

        # Frame de configuración (se muestra tras autenticación)
        self.config_frame = ttk.Frame(self, padding=10)
        self.entries = {}
        for idx, key in enumerate(self.fields):
            ttk.Label(self.config_frame, text=key).grid(row=idx, column=0, sticky="w", pady=2)
            entry = ttk.Entry(self.config_frame, width=60)
            entry.grid(row=idx, column=1, pady=2)
            self.entries[key] = entry

        ttk.Button(self.config_frame, text="Guardar .env cifrado", command=self.save_encrypted).grid(
            row=len(self.fields), column=0, pady=8
        )
        ttk.Button(self.config_frame, text="Cambiar contraseña admin", command=self.update_admin).grid(
            row=len(self.fields), column=1, pady=8, sticky="w"
        )
        self.config_frame.grid_remove()

    def handle_auth(self):
        email = self.login_email.get().strip()
        password = self.login_password.get()
        if not email or not password:
            messagebox.showerror("Faltan datos", "Introduce correo y contraseña de administrador.")
            return
        app = create_app(os.getenv("FLASK_ENV", "development"))
        ok, msg, _ = verify_or_create_admin(app, email, password)
        if not ok:
            messagebox.showerror("Acceso denegado", msg)
            return
        self.auth_email = email
        self.auth_password = password
        self.populate_entries(email, password)
        self.unlocked = True
        self.login_frame.grid_remove()
        self.config_frame.grid(row=0, column=0, sticky="nsew")
        messagebox.showinfo("Acceso concedido", msg + " Configuración desbloqueada.")

    def populate_entries(self, admin_email, admin_password):
        # Cargamos valores existentes (sin exponer antes de autenticación)
        for key, entry in self.entries.items():
            entry.delete(0, tk.END)
            entry.insert(0, self.env.get(key, ""))
        # Guardamos en memoria las credenciales para el guardado cifrado
        self.auth_email = admin_email
        self.auth_password = admin_password

    def save_encrypted(self):
        if not self.unlocked:
            messagebox.showerror("No autenticado", "Primero accede con el administrador.")
            return
        updated = {}
        for key, entry in self.entries.items():
            plain = entry.get()
            if key in {"SECRET_KEY", "SECURITY_PASSWORD_SALT", "ADMIN_PASSWORD", "MAIL_PASSWORD"}:
                updated[key] = encrypt_value(plain) if plain else ""
            else:
                updated[key] = plain
        # Incluimos admin encriptado aunque no se muestre en el formulario
        updated["ADMIN_EMAIL"] = self.auth_email or ""
        updated["ADMIN_PASSWORD"] = encrypt_value(self.auth_password) if self.auth_password else ""
        save_env(updated)
        messagebox.showinfo("Guardado", "Valores guardados en .env (cifrados donde aplica).")

    def update_admin(self):
        if not self.unlocked:
            messagebox.showerror("No autenticado", "Primero accede con el administrador.")
            return
        if not self.auth_email:
            messagebox.showerror("No hay admin", "No hay correo de admin cargado.")
            return
        new_password = simpledialog.askstring(
            "Nueva contraseña",
            "Introduce la nueva contraseña para el administrador:",
            show="*",
            parent=self,
        )
        if not new_password:
            messagebox.showinfo("Sin cambios", "La contraseña no ha cambiado.")
            return
        app = create_app(os.getenv("FLASK_ENV", "development"))
        if update_admin_password(app, self.auth_email, new_password):
            self.auth_password = new_password
            # Actualizamos también el .env en memoria
            self.env["ADMIN_EMAIL"] = self.auth_email
            self.env["ADMIN_PASSWORD"] = encrypt_value(new_password)
            messagebox.showinfo("Actualizado", "Contraseña de administrador actualizada.")
        else:
            messagebox.showerror("Error", "No se pudo actualizar la contraseña.")


if __name__ == "__main__":
    EnvManagerApp().mainloop()
