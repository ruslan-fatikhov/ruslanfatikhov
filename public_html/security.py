import os
import secrets
import time
from datetime import timedelta

from flask import abort, g, redirect, request, session
from werkzeug.middleware.proxy_fix import ProxyFix
from storage import DATA_DIR, transaction, read_json, write_json, content_revision


def configure_security(app):
    with transaction():
        secret = os.environ.get('SECRET_KEY', '')
        if secret and (len(secret) < 32 or secret == 'dev-secret-key-change-me'):
            raise RuntimeError('SECRET_KEY must contain at least 32 random characters')
        if not secret:
            path = DATA_DIR / '.session-secret'
            if not path.exists():
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as handle:
                    handle.write(secrets.token_hex(32))
            secret = path.read_text().strip()
    local = os.getenv('APP_ENV') == 'development'
    dev_admin_login = local and os.getenv('DEV_ADMIN_LOGIN') == '1'
    app.config.update(APP_ENV='development' if local else 'production', DEV_ADMIN_LOGIN=dev_admin_login,
                      SECRET_KEY=secret, SESSION_COOKIE_SECURE=not local,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      MAX_CONTENT_LENGTH=32 * 1024 * 1024, MAX_FORM_MEMORY_SIZE=4 * 1024 * 1024)
    # Only enable behind a proxy that removes client-supplied forwarded headers.
    hops = int(os.getenv('TRUSTED_PROXY_HOPS', '0'))
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0, x_prefix=0)
    hosts = os.getenv('TRUSTED_HOSTS', '')
    if hosts:
        app.config['TRUSTED_HOSTS'] = [host.strip() for host in hosts.split(',')]

    @app.before_request
    def protect_request():
        if not local and not request.is_secure:
            return redirect(request.url.replace('http://', 'https://', 1), code=308)
        if request.path == '/static/files/cv.pdf':
            return redirect('/cv/download', code=308)
        if request.path.startswith('/admin'):
            # Capture before reading form data; never hold a lock across the request.
            g.content_revision = content_revision()
            if 'csrf_token' not in session:
                session['csrf_token'] = secrets.token_urlsafe(32)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                origin = request.headers.get('Origin')
                if origin and origin != request.host_url.rstrip('/'):
                    abort(403, 'Недопустимый Origin')
                token = request.form.get('csrf_token', '')
                if not secrets.compare_digest(token.encode(), session['csrf_token'].encode()):
                    abort(403, 'Недействительный CSRF-токен')
                if request.path not in ('/admin/login', '/admin/logout') and session.get('admin_logged_in'):
                    if request.form.get('revision') != g.content_revision:
                        abort(409, 'Данные изменены в другой вкладке. Обновите страницу перед сохранением.')
                if request.path == '/admin/login':
                    with transaction():
                        try:
                            attempts = read_json('.login-attempts.json')
                        except FileNotFoundError:
                            attempts = {}
                        now = time.time()
                        attempts = {key: value for key, value in attempts.items() if value['until'] > now}
                        # Global account limit also prevents bypass by rotating IP addresses.
                        for key, limit in (('account', 30), ('ip:' + (request.remote_addr or ''), 10)):
                            entry = attempts.setdefault(key, {'count': 0, 'until': now + 900})
                            if entry['count'] >= limit:
                                abort(429, 'Слишком много попыток. Повторите через 15 минут.')
                            entry['count'] += 1
                        write_json('.login-attempts.json', attempts)

    @app.teardown_request
    def unlock_request(error):
        if not g.get('uploads_committed', False):
            for path in g.pop('uploaded_paths', []):
                path.unlink(missing_ok=True)

    @app.after_request
    def security_headers(response):
        if request.endpoint == 'static':
            if not local and request.args.get('v'):
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            else:
                response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith('/admin'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.context_processor
    def form_security():
        return {'csrf_token': session.get('csrf_token', ''),
                'revision': g.get('content_revision', '')}
