import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def settings():
    return {
        "DATABASE": os.getenv("DATABASE", str(ROOT / "instance" / "experiment.sqlite")),
        "SECRET_KEY": os.getenv("SECRET_KEY"),
        "ADMIN_USERNAME": os.getenv("ADMIN_USERNAME"),
        "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
        "LOCAL_DEVELOPMENT": os.getenv("LOCAL_DEVELOPMENT", "0") == "1",
        "EXPERIMENT_START": os.getenv("EXPERIMENT_START", ""),
        "EXPERIMENT_END": os.getenv("EXPERIMENT_END", ""),
        "DATA_RELIABLE": os.getenv("DATA_RELIABLE", "1") == "1",
        "DATA_QUALITY_REASON": os.getenv("DATA_QUALITY_REASON", ""),
        "NOTICE_TEXT": os.getenv("NOTICE_TEXT", ""),
        "OPERATIONS_CONFIRMED": os.getenv("OPERATIONS_CONFIRMED", "0") == "1",
        "EXPOSURE_POLICY": os.getenv("EXPOSURE_POLICY", "cards"),
        "DISPLAY_TIMEZONE": os.getenv("DISPLAY_TIMEZONE", "Asia/Seoul"),
        "MAX_CONTENT_LENGTH": 32768,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
    }
