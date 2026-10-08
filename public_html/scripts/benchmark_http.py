"""Compare loopback HTTP TTFB; pass baseline and updated server base URLs."""
import json
import statistics
import subprocess
import sys
results = {}
for base in sys.argv[1:]:
    pages = {}
    for path in ('/', '/cities', '/timebox-camera'):
        times = []
        for _ in range(31):
            run = subprocess.run(['curl', '-sS', '--max-time', '10', '-o', '/dev/null', '-w', '%{http_code} %{time_starttransfer}', base + path], capture_output=True, text=True, check=True)
            code, elapsed = run.stdout.split()
            assert code == '200', (base, path, code)
            times.append(float(elapsed) * 1000)
        pages[path] = {'first_ms': round(times[0], 2), 'median_ms': round(statistics.median(times[1:]), 2), 'p95_ms': round(sorted(times[1:])[28], 2)}
    results[base] = pages
print(json.dumps(results, indent=2))
