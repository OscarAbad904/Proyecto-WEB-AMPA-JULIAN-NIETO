from dotenv import load_dotenv
import os
from config import unwrap_fernet_json_layers
load_dotenv()
print(unwrap_fernet_json_layers(os.getenv('GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON')))
