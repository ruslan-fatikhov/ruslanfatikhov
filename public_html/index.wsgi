import os
import site
import sys
import traceback
from glob import glob


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYDEPS = os.path.join(PROJECT_ROOT, "pydeps")
LOG_PATH = os.path.join(PROJECT_ROOT, "wsgi_error.log")
HOME_DIR = os.path.expanduser("~")


def _add_site_dir(path):
    if os.path.isdir(path):
        site.addsitedir(path)


def _bootstrap_python_paths():
    candidate_dirs = [
        PYDEPS,
        os.path.join(PROJECT_ROOT, "venv", "lib"),
        os.path.join(PROJECT_ROOT, ".venv", "lib"),
        os.path.join(HOME_DIR, ".local", "lib"),
    ]

    for lib_root in candidate_dirs:
        if not os.path.isdir(lib_root):
            continue

        # Support both direct site-packages directory and pythonX.Y/site-packages layout.
        _add_site_dir(lib_root)
        for site_packages in glob(os.path.join(lib_root, "python*", "site-packages")):
            _add_site_dir(site_packages)


_bootstrap_python_paths()

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.chdir(PROJECT_ROOT)

from env_utils import load_dotenv_file

load_dotenv_file(os.path.join(PROJECT_ROOT, ".env"))


def _log_error(message):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


try:
    from app import app as flask_app
except Exception:
    _log_error("Python executable: {0}".format(sys.executable))
    _log_error("Python version: {0}".format(sys.version))
    _log_error("sys.path:\n{0}".format("\n".join(sys.path)))
    _log_error(traceback.format_exc())

    def application(environ, start_response):
        start_response(
            "500 Internal Server Error",
            [("Content-Type", "text/plain; charset=utf-8")],
        )
        return [b"Internal Server Error"]
else:

    def application(environ, start_response):
        try:
            environ["SCRIPT_NAME"] = ""

            path_info = environ.get("PATH_INFO", "")
            if not path_info:
                request_uri = environ.get("REQUEST_URI", "")
                if request_uri:
                    path = request_uri.split("?", 1)[0]
                    environ["PATH_INFO"] = path or "/"
                else:
                    environ["PATH_INFO"] = "/"

            return flask_app(environ, start_response)
        except Exception:
            _log_error(traceback.format_exc())
            start_response(
                "500 Internal Server Error",
                [("Content-Type", "text/plain; charset=utf-8")],
            )
            return [b"Internal Server Error"]
