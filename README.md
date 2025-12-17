# AMPA Julián Nieto — Configuración de credenciales Google (Drive + Calendar)

Este proyecto usa OAuth de usuario para:

- Subir imágenes y backups a **Google Drive**
- Leer eventos desde **Google Calendar**

La autenticación se basa en dos ficheros/JSON:

- `credentials_drive_oauth.json` (credenciales OAuth del **cliente**)
- `token_drive.json` (token OAuth del **usuario** autorizado)

Ambos están en `.gitignore` y **no deben subirse a Git**.

---

## 1) Requisitos previos

- Python y entorno virtual activado
- Acceso a Google Cloud Console con una cuenta administradora del proyecto
- La cuenta de Google con la que vas a autorizar debe tener acceso al Drive/Shared Drive y al Calendar que se vaya a usar

APIs necesarias en Google Cloud:

- **Google Drive API**
- **Google Calendar API**

---

## 2) Crear `credentials_drive_oauth.json` (Google Cloud Console)

1. Entra en Google Cloud Console y selecciona (o crea) un **proyecto**.
2. Ve a `APIs & Services` → `Library` y habilita:
   - `Google Drive API`
   - `Google Calendar API`
3. Ve a `APIs & Services` → `OAuth consent screen`:
   - Configura el nombre de la app y el tipo (interno/externo según tu caso).
   - Añade tu usuario como “test user” si estás en modo prueba.
4. Ve a `APIs & Services` → `Credentials` → `Create Credentials` → `OAuth client ID`:
   - Tipo: **Desktop app** (recomendado para `flask regenerate-google-token`, usa `run_local_server`).
5. Descarga el JSON y guárdalo como:
   - `credentials_drive_oauth.json` en la **raíz** del proyecto (`D:\Proyecto-WEB-AMPA-JULIAN-NIETO\credentials_drive_oauth.json`).

---

## 3) Generar `token_drive.json` (autorización del usuario)

Esto se hace **en local** porque abre navegador para completar OAuth.

1. Asegúrate de tener `credentials_drive_oauth.json` en la raíz.
2. Ejecuta:

   - Si `flask` está disponible en tu venv:  
     `flask regenerate-google-token`
   - Si no, usa:  
     `python -m flask --app app.py regenerate-google-token`

3. Se abrirá el navegador: elige la **cuenta correcta** y autoriza todos los permisos solicitados.
4. Se generará `token_drive.json` en la raíz del proyecto.

Notas importantes:

- Si autorizas con otra cuenta, verás errores tipo “File not found (404)” al intentar acceder a carpetas que pertenecen a otra cuenta/drive.
- Si cambias el `credentials_drive_oauth.json` (otro OAuth client), puede que tengas que regenerar el token.

---

## 4) Crear/seleccionar carpetas de Drive y guardar IDs

El proyecto guarda IDs de carpetas para organizar recursos:

- `GOOGLE_DRIVE_ROOT_FOLDER_ID` (carpeta raíz “WEB Ampa” o la que elijas)
- `GOOGLE_DRIVE_NEWS_FOLDER_ID`
- `GOOGLE_DRIVE_EVENTS_FOLDER_ID`
- `GOOGLE_DRIVE_DOCS_FOLDER_ID`
- `GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID`

### Opción A (recomendada): comando CLI

Ejecuta:

- `flask setup-drive-folders`
- o: `python -m flask --app app.py setup-drive-folders`

Te imprimirá los IDs. Copia y pega esos valores en tu `.env` (local) o en las variables de entorno del despliegue.

### Opción B: desde el gestor web (`env_manager_server.py`)

1. Arranca el gestor:
   - `python env_manager_server.py`
2. Abre `http://localhost:5050`
3. Usa la opción de “Setup Drive folders” para que escriba los IDs en `.env`.

Si tenías un `GOOGLE_DRIVE_ROOT_FOLDER_ID` antiguo que ahora da 404, el gestor intentará detectar/crear una carpeta accesible y actualizar `.env`.

---

## 5) Configurar Google Calendar

Variables principales:

- `GOOGLE_CALENDAR_ID` (por ejemplo `primary` o un ID tipo `xxxxx@group.calendar.google.com`)
- `GOOGLE_CALENDAR_CACHE_TTL` (segundos; por defecto 600)

El token generado en el paso 3 ya incluye el scope de Calendar:

- `https://www.googleapis.com/auth/calendar.events.readonly`

---

## 6) Dónde copiar cada cosa (local vs Render)

### En local (desarrollo)

- Archivo: `credentials_drive_oauth.json` → **raíz del proyecto**
- Archivo: `token_drive.json` → **raíz del proyecto**
- Variables en `.env`:
  - `GOOGLE_DRIVE_ROOT_FOLDER_ID`, `GOOGLE_DRIVE_*_FOLDER_ID`
  - `GOOGLE_CALENDAR_ID`, `GOOGLE_CALENDAR_CACHE_TTL`

### En Render / producción

En producción no es práctico depender del “login por navegador”. La forma recomendada es subir los JSON como **variables de entorno**:

- `GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON` → contenido JSON de `credentials_drive_oauth.json`
- `GOOGLE_DRIVE_TOKEN_JSON` → contenido JSON de `token_drive.json`

Este proyecto soporta valores **encriptados con Fernet** (recomendado). La clave se lee desde `fernet.key`.

#### Encriptar y copiar a variables de entorno

1. Asegúrate de tener `fernet.key` en la raíz (no se versiona).
2. Ejecuta en local:

   - Encriptar credenciales:
     - `python -c "from config import encrypt_value; print(encrypt_value(open('credentials_drive_oauth.json','rb').read()))"`
   - Encriptar token:
     - `python -c "from config import encrypt_value; print(encrypt_value(open('token_drive.json','rb').read()))"`

3. Copia los resultados y pégalos en Render como:
   - `GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON=<valor_encriptado>`
   - `GOOGLE_DRIVE_TOKEN_JSON=<valor_encriptado>`

Además, configura en Render:

- `GOOGLE_DRIVE_ROOT_FOLDER_ID` y el resto de IDs de carpetas
- `GOOGLE_CALENDAR_ID`

Importante:

- La **misma** `fernet.key` debe estar disponible donde se ejecute la app (local y Render), porque se usa para desencriptar.

---

## 7) Problemas frecuentes

### “File not found (404)” al acceder a una carpeta por ID

Casi siempre es una de estas:

- El token se generó con **otra cuenta** distinta a la que tiene esa carpeta.
- Estás apuntando a un `GOOGLE_DRIVE_ROOT_FOLDER_ID` que no es accesible con el token actual.

Solución rápida:

- Borra/limpia los IDs en `.env` y ejecuta `setup-drive-folders` para regenerarlos con la cuenta correcta.

### “No se encontró el archivo de credenciales OAuth”

Comprueba:

- Que `credentials_drive_oauth.json` existe en la raíz, o
- Que has configurado `GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON` (en local o en Render).

---

## 8) Variables de entorno relevantes (resumen)

- Drive OAuth:
  - `GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE` (por defecto `credentials_drive_oauth.json`)
  - `GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON` (contenido JSON; opcional, recomendado en Render)
  - `GOOGLE_DRIVE_TOKEN_JSON` (contenido JSON; recomendado en Render)
- Drive carpetas:
  - `GOOGLE_DRIVE_ROOT_FOLDER_NAME` (por defecto `WEB Ampa`)
  - `GOOGLE_DRIVE_ROOT_FOLDER_ID`
  - `GOOGLE_DRIVE_NEWS_FOLDER_NAME` / `GOOGLE_DRIVE_NEWS_FOLDER_ID`
  - `GOOGLE_DRIVE_EVENTS_FOLDER_NAME` / `GOOGLE_DRIVE_EVENTS_FOLDER_ID`
  - `GOOGLE_DRIVE_DOCS_FOLDER_NAME` / `GOOGLE_DRIVE_DOCS_FOLDER_ID`
  - `GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME` / `GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID`
  - `GOOGLE_DRIVE_SHARED_DRIVE_ID` (si usas Shared Drive)
- Calendar:
  - `GOOGLE_CALENDAR_ID`
  - `GOOGLE_CALENDAR_CACHE_TTL`

---

## 9) Alta pública de socios (registro/login)

Flujo:

1. **Registro público**: `GET/POST /socios/register`
   - Crea usuario con rol **Socio**.
   - `email_verified=False` y `registration_approved=False`.
   - Guarda aceptación de privacidad (`privacy_accepted_at`, `privacy_version`).
   - Envía:
     - Email de verificación al socio (enlace `GET /verify-email/<token>`)
     - Email al AMPA con asunto **exacto**: `Nuevo registro de Socio`
2. **Verificación de correo**: `GET /verify-email/<token>`
   - Marca `email_verified=True`.
3. **Aprobación por admin**: `POST /admin/usuarios/<id>/aprobar` (UI en `/admin/usuarios`)
   - Marca `registration_approved=True`, `approved_at` y `approved_by_id`.
   - Envía email con enlace para establecer contraseña: `GET/POST /set-password/<token>`
4. **Login**: `POST /socios/login`
   - Bloqueado si `email_verified` es `False` o `registration_approved` es `False`.

Variables de entorno relacionadas:

- SMTP:
  - `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`
- Destinatario AMPA (notificación de altas):
  - `MAIL_AMPA_RECIPIENT`
- Expiración de tokens (segundos):
  - `EMAIL_VERIFICATION_TOKEN_MAX_AGE` (por defecto 86400)
  - `SET_PASSWORD_TOKEN_MAX_AGE` (por defecto 86400)
- Privacidad:
  - `PRIVACY_POLICY_VERSION`
