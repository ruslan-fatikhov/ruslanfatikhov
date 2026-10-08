"""Measure public GET while an admin handler takes 200 ms (no content writes)."""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['APP_ENV'] = 'development'
# Optional baseline source directory for reproducing the old locking behavior.
if len(sys.argv) > 1:
    import storage, security
    for module in (storage, security):
        exec(compile((Path(sys.argv[1]) / (module.__name__ + '.py')).read_text(), module.__file__, 'exec'), module.__dict__)
from app import create_app
app = create_app()
app.config['APP_ENV'] = 'development'
entered = threading.Event()
@app.get('/admin/performance-probe')
def slow_admin():
    entered.set()
    time.sleep(0.2)
    return 'ok'
result = {}
for path in ('/', '/cities', '/timebox-camera'):
    app.test_client().get(path)
    entered.clear()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(lambda: app.test_client().get('/admin/performance-probe'))
        assert entered.wait(3)
        start = time.perf_counter()
        response = app.test_client().get(path)
        result[path] = round((time.perf_counter() - start) * 1000, 2)
        assert response.status_code == 200
        future.result()
print(json.dumps(result, indent=2))
