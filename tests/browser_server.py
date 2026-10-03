import sys
import os
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.db import init_db
from werkzeug.serving import make_server

with tempfile.TemporaryDirectory() as directory:
    app = create_app({"DATABASE": str(Path(directory) / "browser.sqlite"), "SECRET_KEY": "browser-test-secret", "LOCAL_DEVELOPMENT": True, "TESTING": False, "EXPOSURE_POLICY": os.getenv("BROWSER_TEST_POLICY", "pending"), "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "browser-password", "EXPERIMENT_START": "", "EXPERIMENT_END": ""})
    with app.app_context():
        init_db()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    print(server.server_port, flush=True)
    server.serve_forever()