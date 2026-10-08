import os
from flask import Flask
from env_utils import load_dotenv_file

load_dotenv_file()
from routes import register_routes
from security import configure_security


def create_app():
    app = Flask(__name__)
    configure_security(app)
    app.config['PREFERRED_URL_SCHEME'] = 'https'
    register_routes(app)
    return app


# Running this file directly is the explicit local development entry point.
if __name__ == '__main__':
    os.environ.setdefault('APP_ENV', 'development')
app = create_app()

if __name__ == '__main__':
    app.run(port=5044, debug=os.getenv('FLASK_DEBUG') == '1')
