"""Punto de entrada para la aplicación AMPA Julián Nieto.

Este archivo ha sido refactorizado para utilizar la estructura modular en el directorio `app/`.
Toda la lógica de modelos, rutas y configuración se encuentra ahora en sus respectivos módulos.
"""

import os
from app import create_app
from config import get_int_env

# Crear la aplicación utilizando la fábrica
app = create_app(os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    # Ejecutar la aplicación
    port = get_int_env("PORT", 5050)
    print(f"🚀 Iniciando servidor en el puerto {port}...")
    app.run(host="0.0.0.0", port=port)
