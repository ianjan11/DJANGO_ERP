from .base import *
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv(BASE_DIR / ".env")

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]

# Ensure debug toolbar middleware is active locally
if "debug_toolbar" in INSTALLED_APPS and "debug_toolbar.middleware.DebugToolbarMiddleware" not in MIDDLEWARE:
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")