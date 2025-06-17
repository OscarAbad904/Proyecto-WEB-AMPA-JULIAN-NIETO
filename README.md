# Web AMPA Julián Nieto Tapia

Este repositorio contiene el código del portal de la Asociación de Madres y Padres de Alumnos del colegio **Julián Nieto Tapia**. La aplicación se ejecuta con [Flask](https://flask.palletsprojects.com/) y sirve una página principal con HTML, CSS y JavaScript.

## Requisitos

- Python 3.10 o superior
- `pip` para instalar las dependencias del archivo `requirements.txt`

## Puesta en marcha

1. Crea un entorno virtual opcional y actívalo:
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows `venv\Scripts\activate`
   ```
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Copia `.env.example` a `.env` y ajusta las variables `SECRET_KEY`, `SHUTDOWN_SECRET_KEY`, `DB_USER` y `DB_PASSWORD` si se utiliza la base de datos externa.
4. Ejecuta la aplicación con:
   ```bash
   python app.py
   ```
5. Abre `http://localhost:5000/` en tu navegador.

## Estructura

- **app.py** – Servidor Flask con rutas para la página principal y modales de inicio de sesión y registro.
- **templates/** – Plantillas HTML (actualmente `AMPA.html`).
- **static/** – Recursos estáticos: hojas de estilo, JavaScript e imágenes.
- **updater.py** – Script opcional para actualizar la versión empaquetada (`app.exe`) en entornos Windows.
- **config.py** – Carga de variables de entorno definidas en `.env`.

## Licencia

El código se publica bajo los términos de la licencia MIT incluida en el archivo `LICENSE`.

## Información ampliada

Para conocer con más detalle las actividades recientes, la junta directiva y otras
iniciativas de la asociación, consulta el documento [AMPA_INFO.md](AMPA_INFO.md).
