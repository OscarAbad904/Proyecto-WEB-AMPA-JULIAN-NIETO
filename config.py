from dotenv import load_dotenv
import os

load_dotenv()

# Variables de entorno principales
SECRET_KEY = os.getenv('SECRET_KEY')
SHUTDOWN_SECRET_KEY = os.getenv('SHUTDOWN_SECRET_KEY')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
