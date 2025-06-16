# Proyectos Web EMESA

Este repositorio contiene una aplicación web desarrollada en Python con Flask que agrupa distintas utilidades internas de EMESA. Incluye varias páginas HTML y consultas a bases de datos ODBC, así como un sistema de autenticación basado en JSON Web Tokens (JWT).

## Requisitos

- Python 3.10 o superior
- `pip` para instalar dependencias
- Librerías incluidas en `requirements.txt`:
  - Flask
  - flask_jwt_extended
  - pyodbc
  - python-dotenv
  - requests (usada por `updater.py`)

## Uso rápido

1. Crea un entorno virtual y actívalo:
   ```bash
   python -m venv venv
   source venv/bin/activate   # En Windows usa `venv\Scripts\activate`
   ```
2. Instala las dependencias desde `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
3. Copia el archivo `.env.example` a `.env` y ajusta los valores de `SECRET_KEY`, `SHUTDOWN_SECRET_KEY`, `DB_USER` y `DB_PASSWORD`:
   ```bash
   cp .env.example .env
   # Edita .env con tus credenciales
   ```
4. Ejecuta la aplicación:
   ```bash
   python app.py
   ```
La API se iniciará en `http://localhost:5000`.

## Estructura del proyecto

A continuación se describe la organización de archivos y carpetas más relevantes:

- **`app.py`**  
  Módulo principal de la aplicación. Configura Flask, gestiona las rutas, el acceso a las bases de datos y la autenticación con JWT.

- **`templates/`**  
  Plantillas HTML con Jinja2 utilizadas por las distintas vistas (por ejemplo, `main.html`).

- **`static/`**  
  Contiene recursos estáticos y ejemplos de bases SQLite.
  - `static/js`: scripts como `main.js`, `login.js` y `register.js`.
  - `static/css`: hojas de estilo de la interfaz.
  - `static/BaseDatos_Pruebas`: ficheros `.db` consultados por la API.

- **`updater.py`**  
  Script para actualizar el ejecutable (`app.exe`). Comprueba la carpeta `update`, detiene la API mediante `/shutdown_api` y reemplaza el archivo.

- **`build/`** y **`dist/`**  
  Carpetas generadas por PyInstaller al crear el ejecutable.

- **`Prueba-planificador-turnos/`**  
  Ejemplo independiente con HTML y JavaScript para planificar turnos.

### Aspectos importantes

1. **Variables de entorno**: `.env` define `SECRET_KEY`, `SHUTDOWN_SECRET_KEY`, `DB_USER` y `DB_PASSWORD`.
2. **Autenticación**: las vistas utilizan sesiones de Flask y los endpoints emplean JWT.
3. **Bases de datos**: se consulta SQL Server mediante `pyodbc` y se usan ficheros SQLite locales.
4. **Actualización automática**: `updater.py` se basa en la ruta `/shutdown_api` para reemplazar la aplicación en ejecución.

### Recomendaciones para empezar

- Familiarizarse con Flask y las plantillas Jinja2.
- Revisar `flask_jwt_extended` para gestionar JWT.
- Explorar `pyodbc` y la configuración ODBC.
- Analizar los scripts en `static/js` y las hojas de estilo en `static/css`.
- Consultar PyInstaller y los archivos `.spec` si es necesario generar nuevos ejecutables.

## `updater.py`

Opcionalmente, el repositorio incluye `updater.py`, un pequeño script pensado para actualizar la versión empaquetada de la API (`app.exe`). Comprueba si existe un nuevo ejecutable en la carpeta `update`, detiene la API actual y reemplaza el archivo por el nuevo, realizando copias de seguridad si es necesario.

## Licencia

Este proyecto se distribuye bajo los términos de la licencia MIT. Consulta el archivo `LICENSE` para más información.
