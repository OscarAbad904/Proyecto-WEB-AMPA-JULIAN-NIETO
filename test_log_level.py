
import os
from dotenv import load_dotenv
import logging

# Create a dummy .env file
with open(".env.test", "w") as f:
    f.write("LOG_LEVEL=\n")

load_dotenv(".env.test")

log_level = os.getenv("LOG_LEVEL") or "INFO"
print(f"LOG_LEVEL from env: '{os.getenv('LOG_LEVEL')}'")
print(f"Resolved LOG_LEVEL: '{log_level}'")

try:
    logging.basicConfig(level=log_level)
    print("Logging configured successfully")
except ValueError as e:
    print(f"Error configuring logging: {e}")

# Clean up
os.remove(".env.test")
