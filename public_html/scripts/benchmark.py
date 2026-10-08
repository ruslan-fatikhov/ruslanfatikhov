"""Local Flask timings: first request and median/p95 of 30 warm requests."""
import json
import os
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['APP_ENV'] = 'development'
from app import create_app
app = create_app()
client = app.test_client()
result = {}
for path in ('/', '/cities', '/timebox-camera'):
    values = []
    for _ in range(31):
        start = time.perf_counter()
        response = client.get(path)
        values.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200
    result[path] = {'first_ms': round(values[0], 2), 'median_ms': round(statistics.median(values[1:]), 2), 'p95_ms': round(sorted(values[1:])[28], 2), 'html_bytes': len(response.data)}
print(json.dumps(result, indent=2))
