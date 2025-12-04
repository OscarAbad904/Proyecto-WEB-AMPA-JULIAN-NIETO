import os

from app import create_app
from config import get_int_env

app = create_app(os.getenv("FLASK_ENV", "development"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=get_int_env("PORT", 3000))
