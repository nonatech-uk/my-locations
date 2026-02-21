import os
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

# FollowMee API
FOLLOWMEE_USERNAME = os.environ["FOLLOWMEE_USERNAME"]
FOLLOWMEE_API_KEY = os.environ["FOLLOWMEE_API_KEY"]
FOLLOWMEE_DEVICE_ID = os.environ["FOLLOWMEE_DEVICE_ID"]

# Import settings
DEVICE_ID = os.environ.get("DEVICE_ID", "followmee")
KML_DIR = os.environ.get("KML_DIR", "/home/stu/kml")
