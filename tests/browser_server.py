import sys
import os
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.db import init_db
from werkzeug.serving import make_server

with tempfile.TemporaryDirectory() as directory:
    app = create_app({"DATABASE_URL": "", "VERCEL": False, "DATABASE": str(Path(directory) / "browser.sqlite"), "SECRET_KEY": "browser-test-secret", "LOCAL_DEVELOPMENT": True, "TESTING": False, "EXPOSURE_POLICY": os.getenv("BROWSER_TEST_POLICY", "pending"), "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "browser-password", "EXPERIMENT_START": "", "EXPERIMENT_END": ""})
    with app.app_context():
        init_db()
    if os.getenv('BROWSER_DASHBOARD_FIXTURE') == '1':
        from conftest import Participant
        app.config['TESTING'] = True
        a, b = Participant(app), Participant(app)
        for bid in ('little-prince', 'old-man-and-sea'):
            a.open(bid)
        a.open()
        a.action('emoji', option_id='0')
        a.action('poll', option_id='1')
        a.action('short', body='dashboard short')
        b.action('observe', event_type='community_open')
        target = a.state()['own_reviews']['short']['id']
        b.expose(target)
        b.action('like', target_id=target, active=True)
        b.action('reply', target_id=target, body='dashboard reply')
        app.config['TESTING'] = False
        test = Participant(app)
        test.action('short', body='excluded local short')
    server = make_server("127.0.0.1", 0, app, threaded=True)
    if os.getenv('BROWSER_SEED_FIXTURE') == '1':
        import json
        from urllib.parse import urlsplit
        from app.services.seed import create_links
        app.config['TESTING'] = True
        with app.app_context():
            links, _ = create_links(1, f'http://127.0.0.1:{server.server_port}', 72)
        print(json.dumps({'port': server.server_port, 'seed_path': urlsplit(links[0]).path}), flush=True)
    else:
        print(server.server_port, flush=True)
    server.serve_forever()
