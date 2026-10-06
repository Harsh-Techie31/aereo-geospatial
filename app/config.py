import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./geo_api.db")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))  # 50 MB
MAX_UNZIPPED_BYTES = int(os.getenv("MAX_UNZIPPED_BYTES", 300 * 1024 * 1024))  # zip-bomb guard
