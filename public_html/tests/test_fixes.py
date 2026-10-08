import io
import json
import os
import shutil
import tempfile
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

os.environ['APP_ENV'] = 'development'
from app import create_app
import routes
import storage
from PIL import Image
from werkzeug.datastructures import FileStorage
from flask.sessions import SecureCookieSessionInterface
from image_utils import thumbnail_path


class FixesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        for path in routes.DATA_DIR.glob('*.json'):
            shutil.copy(path, self.data / path.name)
        self.patches = [patch.object(storage, 'DATA_DIR', self.data),
                        patch.object(routes, 'DATA_DIR', self.data),
                        patch.object(routes, 'CITIES_DIR', self.data / 'cities'),
                        patch.object(routes, 'COLLECTIONS_DIR', self.data / 'uploads')]
        for item in self.patches: item.start()
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def credentials(self, admin=False):
        self.client.get('/admin/login')
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = admin
            token = session['csrf_token']
        return {'csrf_token': token, 'revision': storage.content_revision()}

    def test_forged_session_and_csrf(self):
        old = create_app()
        old.secret_key = 'dev-secret-key-change-me'
        cookie = SecureCookieSessionInterface().get_signing_serializer(old).dumps({'admin_logged_in': True})
        self.client.set_cookie('session', cookie)
        self.assertEqual(self.client.get('/admin').status_code, 302)
        form = self.credentials(True)
        self.assertEqual(self.client.post('/admin/books', data={}).status_code, 403)
        self.assertEqual(self.client.post('/admin/books', data=form, headers={'Origin': 'https://evil.test'}).status_code, 403)
        form['revision'] = 'stale'
        self.assertEqual(self.client.post('/admin/books', data=form).status_code, 409)
        self.assertEqual(self.client.get('/admin/logout').status_code, 405)

    def test_login_unicode_rate_limit_and_2fa(self):
        form = self.credentials()
        form['password'] = 'пароль'
        self.assertEqual(self.client.post('/admin/login', data=form).status_code, 200)
        for _ in range(9): self.client.post('/admin/login', data=form)
        self.assertEqual(self.client.post('/admin/login', data=form).status_code, 429)

    def test_valid_two_factor_login(self):
        secret = 'JBSWY3DPEHPK3PXP'
        form = self.credentials()
        with patch.object(routes, 'ADMIN_PASSWORD', 'пароль-test'), patch.object(routes, 'ADMIN_TOTP_SECRET', secret):
            response = self.client.post('/admin/login', data={**form, 'password': 'пароль-test'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.get('/admin').status_code, 302)
            response = self.client.post('/admin/login', data={**form, 'stage': 'totp', 'totp_code': routes.generate_totp_code(secret)})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.get('/admin').status_code, 200)

    def test_coordinates_meta_and_feed(self):
        for coords in ([91, 0], [0, 181], ['NaN', 0], [0, 'Infinity']):
            with self.assertRaises(ValueError): routes.parse_city_location(coords)
        self.assertEqual(routes.parse_city_location([-90, 180]), {'lat': -90, 'lng': 180})
        raw = {'collections': [{'id': 'test', 'title': 'Test', 'meta': {'meta': {'note': 'keep'}, 'other': 1}}]}
        normalized = routes.normalize_collections_store(raw)
        self.assertEqual(normalized, routes.normalize_collections_store(normalized))
        self.assertEqual(normalized['collections'][0]['meta'], {'note': 'keep', 'other': 1})
        properties = routes.normalize_collection_property_rows([
            {'key': 'model', 'label': {'ru': 'Модель', 'en': 'Model'}},
            {'key': 'year', 'label': 'Year'},
        ])
        self.assertEqual(properties[0]['label'], {'ru': 'Модель', 'en': 'Model'})
        self.assertEqual(properties[1]['label'], {'ru': 'Year', 'en': 'Year'})
        self.assertEqual(routes.collection_property_label(properties[0], 'en'), 'Model')
        routes.normalize_feed_rows(routes.load_json('feed.json'))
        self.assertTrue(routes.find_content_file(routes.POSTS_DIR / 'qook-easy', 'ru').exists())

    def test_upload_validation_and_rollback(self):
        out = io.BytesIO()
        Image.new('RGB', (10, 10)).save(out, 'JPEG')
        good = FileStorage(stream=io.BytesIO(out.getvalue()), filename='good.jpg')
        bad = FileStorage(stream=io.BytesIO(b'not an image'), filename='bad.jpg')
        with self.assertRaises(ValueError): routes.save_uploaded_collection_images([good, bad])
        self.assertEqual(list(routes.COLLECTIONS_DIR.iterdir()), [])
        bad = FileStorage(stream=io.BytesIO(out.getvalue()), filename='bad.png')
        with self.assertRaises(ValueError): routes.save_uploaded_collection_images([bad])

    def test_admin_city_create_uploads_originals_and_english_fields(self):
        first = io.BytesIO()
        second = io.BytesIO()
        Image.new('RGB', (12, 12), color=(20, 80, 140)).save(first, 'JPEG')
        Image.new('RGB', (14, 10), color=(140, 80, 20)).save(second, 'JPEG')
        originals = [first.getvalue(), second.getvalue()]
        form = self.credentials(True)
        response = self.client.post('/admin/cities/new', data={
            **form,
            'name': 'Тестоград',
            'name_en': 'Testograd',
            'country': 'Тестия',
            'country_en': 'Testia',
            'slug': 'testograd',
            'location': '10, 20',
            'photos': [(io.BytesIO(originals[0]), 'city.jpg'), (io.BytesIO(originals[1]), 'city-2.jpg')],
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        created = next(city for city in routes.get_cities() if city['slug'] == 'testograd')
        self.assertEqual(created['name_en'], 'Testograd')
        self.assertEqual(created['country_en'], 'Testia')
        saved_files = list((routes.CITIES_DIR / 'testograd').glob('*.jpg'))
        self.assertEqual(len(saved_files), 2)
        self.assertEqual(sorted(path.read_bytes() for path in saved_files), sorted(originals))

    def test_atomic_updates(self):
        routes.save_metrics({'cv_downloads': 0})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: routes.increment_cv_downloads(), range(40)))
        self.assertEqual(routes.get_metrics()['cv_downloads'], 40)
        original = storage.read_json('metrics.json')
        with self.assertRaises(ValueError): storage.write_json('metrics.json', {'bad': float('nan')})
        self.assertEqual(storage.read_json('metrics.json'), original)

    def test_cross_process_updates(self):
        routes.save_metrics({'cv_downloads': 0})
        script = """
import sys
from pathlib import Path
import storage
storage.DATA_DIR = Path(sys.argv[1])
for _ in range(15):
    with storage.transaction():
        metrics = storage.read_json('metrics.json')
        metrics['cv_downloads'] += 1
        storage.write_json('metrics.json', metrics)
"""
        processes = [subprocess.Popen([sys.executable, '-B', '-c', script, str(self.data)]) for _ in range(3)]
        for process in processes:
            self.assertEqual(process.wait(timeout=20), 0)
        self.assertEqual(routes.get_metrics()['cv_downloads'], 45)

    def test_request_size_and_successful_editor_save(self):
        form = self.credentials(True)
        form['payload'] = json.dumps(routes.load_json('feed.json'))
        self.assertEqual(self.client.post('/admin/feed', data=form).status_code, 302)
        self.app.config['MAX_CONTENT_LENGTH'] = 100
        self.assertEqual(self.client.post('/admin/feed', data={'payload': 'x' * 101}).status_code, 413)

    def test_public_pages_and_metadata(self):
        for path in ('/', '/about', '/products', '/cities', '/books', '/collections', '/cv', '/sitemap.xml', '/search.json'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        for collection in routes.get_collection_list():
            path = '/collections/' + collection['id']
            self.assertEqual(self.client.get(path).status_code, 200)
            if collection['items']:
                self.assertEqual(self.client.get(path + '/' + collection['items'][0]['id']).status_code, 200)
        response = self.client.get('/?lang=en', headers={'X-Forwarded-Host': 'evil.test'})
        self.assertNotIn(b'evil.test', response.data)
        self.assertIn(b'<html lang="ru"', response.data)
        self.assertEqual(set(self.client.get('/translations.json').json), {'ru'})
        self.assertIn(b'/cv?lang=ru', self.client.get('/sitemap.xml').data)
        for row in routes.get_published_feed():
            response = self.client.get('/' + row['slug'])
            self.assertEqual(response.status_code, 200, row['slug'])
            self.assertNotIn(b'property="og:image" content="/', response.data)

    def test_download_count(self):
        before = routes.get_metrics()['cv_downloads']
        with self.client.head('/cv/download') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(routes.get_metrics()['cv_downloads'], before)
        self.assertEqual(self.client.get('/static/files/cv.pdf').status_code, 308)
        with self.client.get('/cv/download') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(routes.get_metrics()['cv_downloads'], before + 1)

    def test_production_https(self):
        with patch.dict(os.environ, {'APP_ENV': 'production'}):
            app = create_app()
        client = app.test_client()
        self.assertEqual(client.get('/', base_url='http://localhost').status_code, 308)
        response = client.get('/admin/login', base_url='https://localhost')
        self.assertIn('Secure', response.headers['Set-Cookie'])
        self.assertTrue(response.headers.get('Strict-Transport-Security'))

    def test_dev_admin_login_flag_opens_admin_only_in_development(self):
        with patch.dict(os.environ, {'APP_ENV': 'development', 'DEV_ADMIN_LOGIN': '1'}):
            app = create_app()
        self.assertEqual(app.test_client().get('/admin').status_code, 200)

        with patch.dict(os.environ, {'APP_ENV': 'production', 'DEV_ADMIN_LOGIN': '1'}):
            app = create_app()
        self.assertEqual(app.test_client().get('/admin', base_url='https://localhost').status_code, 302)


if __name__ == '__main__': unittest.main()
