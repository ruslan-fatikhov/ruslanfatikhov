import hashlib
import io
import os
import tempfile
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

STATIC_DIR = Path(__file__).resolve().parent / 'static'
Image.MAX_IMAGE_PIXELS = 24_000_000
FORMATS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP', '.gif': 'GIF'}


def validate_image(uploaded, extension):
    raw = uploaded.read(12 * 1024 * 1024 + 1)
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError('Изображение должно быть не больше 12 МБ')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != FORMATS.get(extension):
                    raise ValueError('Содержимое изображения не соответствует расширению')
                if img.width * img.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError('Изображение должно содержать не больше 24 млн пикселей')
                img.verify()
            with Image.open(io.BytesIO(raw)) as img:
                img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Повреждённое или слишком большое изображение') from exc
    return raw


def thumbnail_path(filename, size=(640, 640), prepare=False):
    """Resolve an existing derivative; only explicit preparation may write files."""
    if not filename:
        return filename
    source = (STATIC_DIR / filename).resolve()
    if not source.is_relative_to(STATIC_DIR) or not source.is_file() or source.suffix.lower() not in FORMATS:
        return filename
    stat = source.stat()
    key = hashlib.sha256(f'{filename}:{stat.st_mtime_ns}:{stat.st_size}:{size}:q85-v2'.encode()).hexdigest()[:24]
    relative = f'img/thumbnails/{key}.webp'
    target = STATIC_DIR / relative
    if not target.exists():
        if not prepare:
            return filename
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with Image.open(source) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail(size, Image.Resampling.LANCZOS)
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGBA' if 'transparency' in img.info else 'RGB')
                fd, temporary = tempfile.mkstemp(dir=target.parent, suffix='.webp')
                os.close(fd)
                img.save(temporary, 'WEBP', quality=85)
                os.replace(temporary, target)
        except (OSError, ValueError, Image.DecompressionBombError):
            return filename
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return relative


def prepare_thumbnail(filename, size=(640, 640)):
    return thumbnail_path(filename, size=size, prepare=True)
