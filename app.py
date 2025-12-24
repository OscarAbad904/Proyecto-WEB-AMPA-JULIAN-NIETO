import os

from app import create_app
from config import get_int_env

app = create_app(os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    run_kwargs = {
        "host": "0.0.0.0",
        "port": get_int_env("PORT", 5000),
        "debug": bool(app.debug),
    }

    # En debug, la sincronización de estilos escribe en assets/ y puede provocar
    # reinicios extra del reloader. Excluimos carpetas de salida generada.
    if app.debug:
        run_kwargs["exclude_patterns"] = [
            "*/assets/*",
            "*\\assets\\*",
            "*/cache/*",
            "*\\cache\\*",
            "*/logs/*",
            "*\\logs\\*",
        ]

    try:
        app.run(**run_kwargs)
    except TypeError:
        # Compatibilidad con versiones antiguas de Flask/Werkzeug sin exclude_patterns
        run_kwargs.pop("exclude_patterns", None)
        app.run(**run_kwargs)
