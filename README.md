# Proyecto Web AMPA Julián Nieto Tapia

Aplicación Flask preparada para registrar socios, publicar noticias y eventos, moderar un foro de sugerencias y gestionar documentos privados.

## Pasos iniciales

1. Copia `.env.example` a `.env` y ajusta credenciales (SQL Server ODBC, SMTP, SECRET_KEY).
2. Instala dependencias: `pip install -r requirements.txt`.
3. Ejecuta `flask db upgrade` para aplicar migraciones iniciales.
4. Crea administrador: `flask create-admin`.
5. Inicia el servidor con `flask run --host 0.0.0.0`.

## Arquitectura

- Base de datos: SQLAlchemy + Flask-Migrate + SQL Server (pyodbc).
- Blueprints: `public`, `members`, `admin`, `api`.
- Servicios: Email, ICS, uploads y búsqueda.
- Frontend: plantillas con `base.html`, componentes, tema claro/oscuro con `theme.js`.
- Pruebas: `tests/` con fixtures y rutas públicas.

## Contenedores

- `Dockerfile`: imagen Python 3.12 que instala dependencias y expone `gunicorn`.
- `docker-compose.yml`: arranca Flask y SQL Server (vía imagen `mcr.microsoft.com/mssql/server`).

## Datos de ejemplo

`data/fixtures.json` contiene roles, usuarios y contenidos básicos para cargar con scripts propios.
