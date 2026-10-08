import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import test_fixes
import routes
import storage
import image_utils


class PerformanceTest(unittest.TestCase):
    setUp = test_fixes.FixesTest.setUp
    tearDown = test_fixes.FixesTest.tearDown
    credentials = test_fixes.FixesTest.credentials

    def test_public_gets_do_not_wait_for_admin_handler(self):
        entered, release = threading.Event(), threading.Event()
        def slow_auth():
            self.assertEqual(getattr(storage._state, 'depth', 0), 0)
            entered.set()
            self.assertTrue(release.wait(5))
            return False
        with patch.object(routes, 'is_admin_authenticated', slow_auth), ThreadPoolExecutor(2) as pool:
            admin = pool.submit(lambda: self.app.test_client().get('/admin'))
            try:
                self.assertTrue(entered.wait(2))
                for path in ('/', '/cities', '/timebox-camera'):
                    public = pool.submit(lambda path=path: self.app.test_client().get(path))
                    self.assertEqual(public.result(timeout=2).status_code, 200)
                self.assertFalse(admin.done())
            finally:
                release.set()
            self.assertEqual(admin.result(timeout=2).status_code, 302)

    def test_public_reads_do_not_acquire_writer_lock(self):
        with patch.object(storage, 'transaction', side_effect=AssertionError('public read took writer lock')):
            for path in ('/', '/cities', '/timebox-camera'):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_revision_is_checked_again_at_commit(self):
        form = self.credentials(True)
        form['payload'] = json.dumps(routes.load_json('feed.json'))
        normalize = routes.normalize_feed_rows
        def concurrent_write(rows):
            result = normalize(rows)
            storage.write_json('home.json', [])
            return result
        with patch.object(routes, 'normalize_feed_rows', concurrent_write):
            response = self.client.post('/admin/feed', data=form)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(storage.read_json('home.json'), [])

    def test_competing_saves_only_one_succeeds(self):
        form = self.credentials(True)
        barrier = threading.Barrier(2)
        normalize = routes.normalize_feed_rows
        def synchronized(rows):
            result = normalize(rows)
            barrier.wait(timeout=3)
            return result
        clients = [self.app.test_client() for _ in range(2)]
        for client in clients:
            with client.session_transaction() as session:
                session.update(admin_logged_in=True, csrf_token=form['csrf_token'])
        feed = routes.load_json('feed.json')
        payloads = []
        for index in range(2):
            rows = json.loads(json.dumps(feed))
            rows[0]['headline']['ru'] = f'Concurrent update {index}'
            payloads.append(json.dumps(rows))
        with patch.object(routes, 'normalize_feed_rows', synchronized), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(client.post, '/admin/feed', data={**form, 'payload': payload}) for client, payload in zip(clients, payloads)]
            self.assertEqual(sorted(f.result(timeout=5).status_code for f in futures), [302, 409])

    def test_upload_work_outside_transaction_and_conflict_rollback(self):
        collection = next(row for row in routes.get_collection_list() if row['items'])
        item = collection['items'][0]
        form = self.credentials(True)
        form['payload'] = json.dumps({'id': item['id'], 'title': item['title'], 'values': item['values']})
        output = io.BytesIO()
        Image.new('RGB', (10, 10)).save(output, 'JPEG')
        form['photos'] = (io.BytesIO(output.getvalue()), 'photo.jpg')
        upload = routes.save_uploaded_collection_images
        def intervening_save(files):
            self.assertEqual(getattr(storage._state, 'depth', 0), 0)
            result = upload(files)
            storage.write_json('home.json', [])
            return result
        before = storage.read_json('collections.json')
        with patch.object(routes, 'save_uploaded_collection_images', intervening_save):
            response = self.client.post(f"/admin/collections/{collection['id']}/items/{item['id']}/edit", data=form)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(storage.read_json('collections.json'), before)
        self.assertEqual(list(routes.COLLECTIONS_DIR.iterdir()), [])

    def test_render_never_generates_thumbnails_and_city_uses_one_cover(self):
        with patch.object(image_utils.Image, 'open', side_effect=AssertionError('GET decoded an image')):
            for path in ('/', '/cities', '/collections', '/books'):
                self.assertEqual(self.client.get(path).status_code, 200)
        with patch.object(routes, 'thumbnail_path', wraps=routes.thumbnail_path) as thumb:
            with patch.object(routes, 'build_city_gallery', side_effect=AssertionError('list built entire gallery')):
                routes.build_city_cards(routes.get_cities(), 'ru')
            self.assertLessEqual(thumb.call_count, len(routes.get_cities()))

    def test_title_fallback_and_no_duplicate_heading(self):
        row = routes.get_feed_item('timebox-camera')
        title = row['headline']['ru']
        html = self.client.get('/timebox-camera').get_data(as_text=True)
        self.assertIn(f'<title>{title}</title>', html)
        self.assertIn(f'property="og:title" content="{title}"', html)
        self.assertIn(f'name="twitter:title" content="{title}"', html)
        self.assertNotIn('class="article__title"', html)
        self.assertNotIn('<iframe', html)
        self.assertIn('data-vimeo="593696263"', html)

    def test_versioning_analytics_and_cache(self):
        source = (routes.BASE_DIR / 'static/js/version-check.js').read_text()
        self.assertNotIn('reload', source)
        self.assertNotIn('caches.delete', source)
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('analytics.js', html)
        self.assertNotIn('mc.yandex', html)
        self.assertIn(f'css/typo.css?v={routes.SITE_VERSION}', html)
        with self.client.get('/static/css/typo.css?v=test') as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-cache')
        with patch.dict('os.environ', {'APP_ENV': 'production'}):
            app = test_fixes.create_app()
        client = app.test_client()
        for path, expected in [('/static/css/typo.css', 'no-cache'), ('/static/css/typo.css?v=test', 'public, max-age=31536000, immutable')]:
            with client.get(path, base_url='https://localhost') as response:
                self.assertEqual(response.headers['Cache-Control'], expected)
        self.assertIn('analytics.js', client.get('/', base_url='https://localhost').get_data(as_text=True))
        self.assertNotIn('analytics.js', client.get('/admin/login', base_url='https://localhost').get_data(as_text=True))
        self.assertNotIn('api.mapbox.com', self.client.get('/cities').get_data(as_text=True))
