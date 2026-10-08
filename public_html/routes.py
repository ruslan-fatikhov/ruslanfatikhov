import json
import math
import os
import re
import secrets
import base64
import binascii
import hashlib
import hmac
import struct
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode, urljoin
from pathlib import Path

from flask import current_app, g, has_request_context, abort, jsonify, make_response, redirect, render_template, request, send_file, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from markdown import Markdown
from werkzeug.utils import secure_filename
from storage import transaction, read_json, write_json, content_revision
from image_utils import validate_image, thumbnail_path, prepare_thumbnail


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONTENT_DIR = BASE_DIR / "content"
POSTS_DIR = CONTENT_DIR / "posts"
PAGES_DIR = CONTENT_DIR / "pages"
CITIES_DIR = BASE_DIR / "static" / "img" / "cities"
COLLECTIONS_DIR = BASE_DIR / "static" / "img" / "collections"
GPX_ROUTES_DIR = DATA_DIR / "gpx_routes"
MOUNTAIN_PEAKS_GPX_PATH = DATA_DIR / "mountain_peaks.gpx"
SUPPORTED_LANGS = ("ru",)
COLLECTION_LABEL_LANGS = ("ru", "en")
SITE_VERSION = "1.1.9"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_TOTP_SECRET = os.getenv("ADMIN_TOTP_SECRET", "")
TOTP_INTERVAL_SECONDS = 30
TOTP_DIGITS = 6
# PDF is private; downloads go through the counted route.
CV_PDF_PATH = BASE_DIR / "data" / "cv.pdf"
# Configure a valid public token separately for each environment.


def load_json(filename):
    return read_json(filename)


def save_json(filename, data):
    # Optimistic read-modify-write: reject any intervening content change.
    # Form parsing, validation and uploads have already finished outside this lock.
    with transaction():
        if (has_request_context() and request.path.startswith('/admin')
                and request.method not in ('GET', 'HEAD', 'OPTIONS')):
            if request.form.get('revision') != content_revision():
                abort(409, 'Данные изменены в другой вкладке. Обновите страницу перед сохранением.')
        write_json(filename, data)


def read_json_or_default(filename, default):
    try:
        return load_json(filename)
    except FileNotFoundError:
        return default


def parse_date(value):
    for fmt in ("%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")

def format_date(value):
    try:
        parsed = parse_date(value)
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return value


def format_date_iso(value):
    try:
        parsed = parse_date(value)
        return parsed.strftime("%Y-%m-%dT00:00:00+00:00")
    except ValueError:
        return ""


def get_translations():
    return {code: value for code, value in load_json("translations.json").items() if code in SUPPORTED_LANGS}


def get_lang(translations):
    lang = request.args.get("lang") or request.cookies.get("lang", "ru")
    return lang if lang in SUPPORTED_LANGS and lang in translations else "ru"


def build_url(base_url, path, lang):
    query = urlencode({"lang": lang})
    return f"{base_url}{path}?{query}"


def parse_front_matter(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n")
    end_idx = None
    for idx in range(1, len(parts)):
        if parts[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, text
    meta_lines = parts[1:end_idx]
    meta = {}
    for line in meta_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"")
    body = "\n".join(parts[end_idx + 1 :])
    return meta, body


def render_markdown(md_text):
    md = Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "sane_lists",
            "smarty",
            "codehilite",
        ]
    )
    return md.convert(md_text)


def load_markdown(path):
    with path.open("r", encoding="utf-8") as handle:
        raw = handle.read()
    meta, body = parse_front_matter(raw)
    html = render_markdown(body)
    return meta, normalize_html(html)


def normalize_html(html):
    # Keep markdown media paths absolute so they work on nested URLs.
    html = re.sub(r'((?:src|href)=["\'])static/', r"\1/static/", html)
    html = re.sub(
        r'((?:src|href)=["\'])(/static/[^"\']+)(["\'])',
        lambda match: (
            f"{match.group(1)}{match.group(2)}&v={SITE_VERSION}{match.group(3)}"
            if "?" in match.group(2)
            else f"{match.group(1)}{match.group(2)}?v={SITE_VERSION}{match.group(3)}"
        ),
        html,
    )
    # Improve loading behavior for article images.
    html = re.sub(r"<img(?![^>]*\bloading=)", '<img loading="lazy" decoding="async"', html)
    return html


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text)


def resolve_cover(slug, meta):
    if meta.get("image"):
        image = meta["image"]
        if image.startswith("/static/"):
            return f"{image}?v={SITE_VERSION}" if "?" not in image else f"{image}&v={SITE_VERSION}"
        return image
    if not slug:
        return ""
    image_path = f"/static/img/blog/{slug}/cover.jpg"
    image_file = BASE_DIR / "static" / "img" / "blog" / slug / "cover.jpg"
    return f"{image_path}?v={SITE_VERSION}" if image_file.exists() else ""


def find_content_file(base_path, lang):
    primary = Path(f"{base_path}-{lang}.md")
    secondary = Path(f"{base_path}.{lang}.md")
    fallback = Path(f"{base_path}-ru.md")
    fallback_secondary = Path(f"{base_path}.ru.md")
    if primary.exists():
        return primary
    if secondary.exists():
        return secondary
    if fallback.exists():
        return fallback
    if fallback_secondary.exists():
        return fallback_secondary
    return None


def list_city_images(city_slug):
    city_dir = CITIES_DIR / city_slug
    if not city_dir.exists():
        return []
    files = [f for f in os.listdir(city_dir) if not f.startswith(".")]
    return sorted(
        [f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    )


def build_city_gallery(city_slug):
    images = list_city_images(city_slug)
    full_images = [image for image in images if "_thumbnail" not in image]
    available = set(images)
    gallery = []
    for image in full_images:
        thumbnail_name = f"{Path(image).stem}_thumbnail{Path(image).suffix}"
        thumb_file = thumbnail_name if thumbnail_name in available else image
        thumb_path = thumbnail_path(f"img/cities/{city_slug}/{thumb_file}")
        gallery.append(
            {
                "thumb": f"/static/{thumb_path}?v={SITE_VERSION}",
                "full": f"/static/img/cities/{city_slug}/{image}?v={SITE_VERSION}",
            }
        )
    return gallery


def parse_city_location(value):
    if isinstance(value, dict):
        lat = value.get("lat")
        lng = value.get("lng")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lat, lng = value[0], value[1]
    else:
        raise ValueError("Локация должна быть в формате 'lat,lng'")

    try:
        lat, lng = float(lat), float(lng)
        if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise ValueError("Координаты вне допустимого диапазона")
        return {"lat": lat, "lng": lng}
    except (TypeError, ValueError) as exc:
        raise ValueError("Локация должна быть в формате 'lat,lng'") from exc


def normalize_city_record(city, index):
    if not isinstance(city, dict):
        raise ValueError(f"Город {index}: некорректный формат")

    raw_country = city.get("country", "")
    raw_city = city.get("city", {})
    name = str(city.get("name") or (raw_city.get("ru", "") if isinstance(raw_city, dict) else "")).strip()
    name_en = str(city.get("name_en") or (raw_city.get("en", "") if isinstance(raw_city, dict) else "")).strip()
    country = str(city.get("country_name") or (raw_country.get("ru", "") if isinstance(raw_country, dict) else raw_country)).strip()
    country_en = str(city.get("country_en") or (raw_country.get("en", "") if isinstance(raw_country, dict) else "")).strip()
    slug = str(city.get("slug", "")).strip().lower()
    location = city.get("location", city.get("coords"))

    if not name:
        raise ValueError(f"Город {index}: заполните название")
    if not country:
        raise ValueError(f"Город {index}: заполните страну")
    name_en = name_en or name
    country_en = country_en or country
    if not slug:
        raise ValueError(f"Город {index}: заполните slug")
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError(f"Город {index}: slug должен содержать только латиницу, цифры и дефис")

    return {
        "name": name,
        "name_en": name_en,
        "country": country,
        "country_en": country_en,
        "location": parse_city_location(location),
        "slug": slug,
    }


def get_cities():
    raw = load_json("cities.json")
    if not isinstance(raw, list):
        raise ValueError("cities.json должен содержать список")
    cities = [normalize_city_record(city, index) for index, city in enumerate(raw, start=1)]
    seen = set()
    for index, city in enumerate(cities, start=1):
        if city["slug"] in seen:
            raise ValueError(f"Город {index}: slug '{city['slug']}' должен быть уникальным")
        seen.add(city["slug"])
    return cities


def save_cities(cities_data):
    save_json("cities.json", cities_data)

def parse_city_form_location(value):
    parts = [part.strip() for part in str(value or "").split(",")]
    if len(parts) != 2:
        raise ValueError("Локация должна быть в формате 'lat,lng'")
    return parse_city_location(parts)


def build_city_cards(cities, lang):
    cards = []
    for city in cities:
        images = [name for name in list_city_images(city["slug"]) if "_thumbnail" not in name]
        thumb_path = ""
        if images:
            path = thumbnail_path(f"img/cities/{city['slug']}/{images[0]}")
            thumb_path = f"/static/{path}?v={SITE_VERSION}"
        cards.append(
            {
                "slug": city["slug"],
                "name": city["name"],
                "country": city["country"],
                "coords": [city["location"]["lat"], city["location"]["lng"]],
                "thumb": thumb_path,
                "count": len(images),
            }
        )
    return sorted(cards, key=lambda card: (card["country"].casefold(), card["name"].casefold()))


def build_city_groups(cities, lang):
    groups = []
    current_country = None
    for card in build_city_cards(cities, lang):
        if card["country"] != current_country:
            groups.append({"country": card["country"], "cities": []})
            current_country = card["country"]
        groups[-1]["cities"].append(card)
    return groups


def build_admin_city_rows(cities):
    cards = {card["slug"]: card for card in build_city_cards(cities, "ru")}
    rows = []
    for city in cities:
        rows.append({**city, "thumb": cards.get(city["slug"], {}).get("thumb", ""), "count": cards.get(city["slug"], {}).get("count", 0)})
    return sorted(rows, key=lambda row: (row["country"].casefold(), row["name"].casefold()))


def build_city_form_state(city=None):
    if city:
        return {
            "name": city["name"],
            "name_en": city["name_en"],
            "country": city["country"],
            "country_en": city["country_en"],
            "slug": city["slug"],
            "location": f"{city['location']['lat']}, {city['location']['lng']}",
        }
    return {"name": "", "name_en": "", "country": "", "country_en": "", "slug": "", "location": ""}


def parse_city_form(form_data):
    name = str(form_data.get("name", "")).strip()
    name_en = str(form_data.get("name_en", "")).strip()
    country = str(form_data.get("country", "")).strip()
    country_en = str(form_data.get("country_en", "")).strip()
    slug = str(form_data.get("slug", "")).strip().lower()
    location_raw = str(form_data.get("location", "")).strip()

    if not name:
        raise ValueError("Название города обязательно")
    if not name_en:
        raise ValueError("Название города на English обязательно")
    if not country:
        raise ValueError("Страна обязательна")
    if not country_en:
        raise ValueError("Страна на English обязательна")
    if not slug:
        raise ValueError("Slug обязателен")
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("Slug должен содержать только латиницу, цифры и дефис")

    return {
        "name": name,
        "name_en": name_en,
        "country": country,
        "country_en": country_en,
        "slug": slug,
        "location": parse_city_form_location(location_raw),
    }


def save_uploaded_city_image(upload, city_slug):
    if not upload or not upload.filename:
        raise ValueError("Загрузите фото города")
    original_name = secure_filename(upload.filename)
    extension = Path(original_name).suffix.lower()
    raw = validate_image(upload, extension)
    city_dir = CITIES_DIR / city_slug
    city_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify_value(Path(original_name).stem) or 'city'}-{secrets.token_hex(12)}{extension}"
    destination = city_dir / filename
    paths = [destination]
    try:
        with destination.open("xb") as handle:
            handle.write(raw)
        static_dir = (BASE_DIR / "static").resolve()
        resolved = destination.resolve()
        if resolved.is_relative_to(static_dir):
            relative = resolved.relative_to(static_dir).as_posix()
            prepared = prepare_thumbnail(relative)
            if prepared != relative:
                paths.append(BASE_DIR / "static" / prepared)
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    if has_request_context():
        g.setdefault("uploaded_paths", []).extend(paths)
    return filename


def save_uploaded_city_images(files, city_slug, require_one=False):
    uploads = [upload for upload in files if upload and upload.filename]
    if require_one and not uploads:
        raise ValueError("Загрузите хотя бы одно фото города")
    return [save_uploaded_city_image(upload, city_slug) for upload in uploads]


def get_mountain_peaks():
    if not MOUNTAIN_PEAKS_GPX_PATH.exists():
        return []
    try:
        root = ET.parse(MOUNTAIN_PEAKS_GPX_PATH).getroot()
    except ET.ParseError:
        return []
    namespace = gpx_namespace(root)
    peaks = []
    for index, waypoint in enumerate(gpx_findall(root, "gpx:wpt", namespace), start=1):
        try:
            latitude = float(waypoint.attrib["lat"])
            longitude = float(waypoint.attrib["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        elevation_raw = gpx_text(waypoint, "gpx:ele", namespace)
        try:
            elevation = None if not elevation_raw else float(elevation_raw)
        except (TypeError, ValueError):
            elevation = None
        peak_id = waypoint.attrib.get("id") or f"peak-{hashlib.sha1(f'{latitude},{longitude},{index}'.encode('utf-8')).hexdigest()[:12]}"
        peaks.append({
            "id": peak_id,
            "name": gpx_text(waypoint, "gpx:name", namespace) or f"Вершина {index}",
            "latitude": latitude,
            "longitude": longitude,
            "elevation": elevation,
            "summitedAt": gpx_text(waypoint, "gpx:time", namespace) or None,
            "isSummited": True,
        })
    return peaks


def save_mountain_peaks(peaks):
    ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
    gpx_ns = "http://www.topografix.com/GPX/1/1"
    root = ET.Element(f"{{{gpx_ns}}}gpx", {
        "version": "1.1",
        "creator": "RuslanFatikhov Admin",
    })
    metadata = ET.SubElement(root, f"{{{gpx_ns}}}metadata")
    name = ET.SubElement(metadata, f"{{{gpx_ns}}}name")
    name.text = "Mountain Peaks"
    for peak in peaks:
        waypoint = ET.SubElement(root, f"{{{gpx_ns}}}wpt", {
            "lat": str(peak["latitude"]),
            "lon": str(peak["longitude"]),
            "id": str(peak["id"]),
        })
        peak_name = ET.SubElement(waypoint, f"{{{gpx_ns}}}name")
        peak_name.text = peak["name"]
        if peak.get("elevation") is not None:
            elevation = ET.SubElement(waypoint, f"{{{gpx_ns}}}ele")
            elevation.text = str(peak["elevation"])
        if peak.get("summitedAt"):
            time_node = ET.SubElement(waypoint, f"{{{gpx_ns}}}time")
            time_node.text = peak["summitedAt"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    temporary = MOUNTAIN_PEAKS_GPX_PATH.with_suffix(".gpx.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    os.replace(temporary, MOUNTAIN_PEAKS_GPX_PATH)


def parse_peak_form(form_data):
    name = form_data.get("name", "").strip()
    if not name:
        raise ValueError("Укажите название вершины")
    try:
        latitude = float(form_data.get("latitude", ""))
        longitude = float(form_data.get("longitude", ""))
    except ValueError as exc:
        raise ValueError("Координаты должны быть числами") from exc
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Координаты вне допустимого диапазона")
    elevation_raw = form_data.get("elevation", "").strip()
    try:
        elevation = None if not elevation_raw else float(elevation_raw)
    except ValueError as exc:
        raise ValueError("Высота должна быть числом") from exc
    return {
        "id": f"peak-{secrets.token_hex(6)}",
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "elevation": elevation,
        "summitedAt": form_data.get("summitedAt", "").strip() or None,
        "isSummited": form_data.get("isSummited") == "on",
    }


def get_gpx_routes():
    if not GPX_ROUTES_DIR.exists():
        return []
    routes_data = []
    for path in sorted(GPX_ROUTES_DIR.glob("*.gpx")):
        try:
            geojson = parse_gpx_file(path)
        except ValueError:
            continue
        routes_data.append({
            "id": path.stem,
            "name": path.stem.replace("-", " ").replace("_", " "),
            "filename": path.name,
            "uploadedAt": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bounds": route_bounds(geojson),
            "geojson": geojson,
        })
    return routes_data


def gpx_namespace(root):
    if root.tag.startswith("{") and "}" in root.tag:
        return {"gpx": root.tag[1:].split("}", 1)[0]}
    return {}


def gpx_findall(node, path, namespace):
    return node.findall(path, namespace) if namespace else node.findall(path.replace("gpx:", ""))


def gpx_text(node, path, namespace):
    match = node.find(path, namespace) if namespace else node.find(path.replace("gpx:", ""))
    return match.text.strip() if match is not None and match.text else ""


def parse_gpx_point(point):
    try:
        latitude = float(point.attrib["lat"])
        longitude = float(point.attrib["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("GPX содержит точку без корректных lat/lon") from exc
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("GPX содержит координаты вне допустимого диапазона")
    return longitude, latitude


def parse_gpx_file(path):
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError("Не удалось прочитать GPX: повреждённый XML") from exc

    namespace = gpx_namespace(root)
    features = []
    fallback_name = path.stem

    for track_index, track in enumerate(gpx_findall(root, "gpx:trk", namespace), start=1):
        track_name = gpx_text(track, "gpx:name", namespace) or fallback_name
        for segment_index, segment in enumerate(gpx_findall(track, "gpx:trkseg", namespace), start=1):
            coordinates = []
            for point in gpx_findall(segment, "gpx:trkpt", namespace):
                longitude, latitude = parse_gpx_point(point)
                elevation_raw = gpx_text(point, "gpx:ele", namespace)
                if elevation_raw:
                    try:
                        coordinates.append([longitude, latitude, float(elevation_raw)])
                    except ValueError:
                        coordinates.append([longitude, latitude])
                else:
                    coordinates.append([longitude, latitude])
            if len(coordinates) >= 2:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "name": track_name,
                        "kind": "track",
                        "segment": segment_index,
                        "track": track_index,
                    },
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                })

    for route_index, route in enumerate(gpx_findall(root, "gpx:rte", namespace), start=1):
        route_name = gpx_text(route, "gpx:name", namespace) or fallback_name
        coordinates = []
        for point in gpx_findall(route, "gpx:rtept", namespace):
            longitude, latitude = parse_gpx_point(point)
            elevation_raw = gpx_text(point, "gpx:ele", namespace)
            if elevation_raw:
                try:
                    coordinates.append([longitude, latitude, float(elevation_raw)])
                except ValueError:
                    coordinates.append([longitude, latitude])
            else:
                coordinates.append([longitude, latitude])
        if len(coordinates) >= 2:
            features.append({
                "type": "Feature",
                "properties": {
                    "name": route_name,
                    "kind": "route",
                    "segment": route_index,
                },
                "geometry": {"type": "LineString", "coordinates": coordinates},
            })

    if not features:
        raise ValueError("В GPX не найдено маршрутов trk/rte с двумя и более точками")
    return {"type": "FeatureCollection", "features": features}


def route_bounds(geojson):
    values = []
    for feature in geojson.get("features", []):
        for coordinate in feature.get("geometry", {}).get("coordinates", []):
            if len(coordinate) >= 2:
                values.append([coordinate[0], coordinate[1]])
    if not values:
        return None
    lng_values = [coordinate[0] for coordinate in values]
    lat_values = [coordinate[1] for coordinate in values]
    return [[min(lng_values), min(lat_values)], [max(lng_values), max(lat_values)]]


def save_uploaded_gpx(upload):
    if not upload or not upload.filename:
        raise ValueError("Выберите GPX-файл")
    filename = secure_filename(upload.filename)
    if not filename.lower().endswith(".gpx"):
        raise ValueError("Поддерживаются только файлы .gpx")
    GPX_ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    name = request.form.get("name", "").strip()
    route_id = secure_filename(name) if name else Path(filename).stem
    route_id = secure_filename(route_id) or f"gpx-{secrets.token_hex(6)}"
    target = GPX_ROUTES_DIR / f"{route_id}.gpx"
    if target.exists():
        target = GPX_ROUTES_DIR / f"{route_id}-{secrets.token_hex(3)}.gpx"
    upload.save(target)
    try:
        parse_gpx_file(target)
    except ValueError:
        target.unlink(missing_ok=True)
        raise
    return target


def is_published(item):
    return item.get("published", True) is True


def get_published_feed():
    return [item for item in load_json("feed.json") if is_published(item)]


def normalize_feed_translations(value, field_name, index):
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} записи #{index} должен быть объектом с языками")

    normalized = {key: str(text).strip() for key, text in value.items()}
    for lang in SUPPORTED_LANGS:
        text = str(value.get(lang, "")).strip()
        if not text:
            raise ValueError(f"{field_name}.{lang} записи #{index} обязателен")
        normalized[lang] = text
    return normalized


def normalize_feed_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("feed.json должен содержать список")

    normalized = []
    used_slugs = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Запись #{index} в feed.json должна быть объектом")

        slug = str(row.get("slug", "")).strip()
        if not slug:
            raise ValueError(f"Slug записи #{index} обязателен")
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError(f"Slug записи #{index} должен содержать только латиницу, цифры и дефис")
        if slug in used_slugs:
            raise ValueError(f"Slug '{slug}' повторяется в feed.json")
        used_slugs.add(slug)

        date = str(row.get("date", "")).strip()
        if not date:
            raise ValueError(f"Дата записи '{slug}' обязательна")
        parse_date(date)

        published = row.get("published", True)
        if not isinstance(published, bool):
            raise ValueError(f"Поле published записи '{slug}' должно быть true или false")

        normalized.append(
            {
                "slug": slug,
                "headline": normalize_feed_translations(row.get("headline"), "headline", index),
                "subline": normalize_feed_translations(row.get("subline"), "subline", index),
                "date": date,
                "published": published,
            }
        )

    return normalized


def parse_feed_form(form):
    if "payload" in form and not any(key.startswith("slug-") for key in form):
        return normalize_feed_rows(json.loads(form.get("payload", "[]")))

    row_indexes = sorted({int(key.split("-", 1)[1]) for key in form if key.startswith("slug-") and key.split("-", 1)[1].isdigit()})
    rows = []
    for index in row_indexes:
        slug = form.get(f"slug-{index}", "").strip()
        headline = {
            "ru": form.get(f"headline_ru-{index}", ""),
            "en": form.get(f"headline_en-{index}", ""),
            "tt": form.get(f"headline_tt-{index}", ""),
        }
        subline = {
            "ru": form.get(f"subline_ru-{index}", ""),
            "en": form.get(f"subline_en-{index}", ""),
            "tt": form.get(f"subline_tt-{index}", ""),
        }
        if not slug and not any(value.strip() for value in headline.values()) and not any(value.strip() for value in subline.values()):
            continue
        rows.append(
            {
                "slug": slug,
                "headline": headline,
                "subline": subline,
                "date": form.get(f"date-{index}", ""),
                "published": form.get(f"published-{index}") == "on",
            }
        )
    return normalize_feed_rows(rows)


def get_feed_slugs():
    slugs = set()
    for item in load_json("feed.json"):
        if isinstance(item, dict):
            slug = str(item.get("slug", "")).strip()
            if slug:
                slugs.add(slug)
    return slugs


def normalize_home_slugs(rows, allowed_slugs=None):
    if not isinstance(rows, list):
        raise ValueError("home.json должен содержать список slug")

    normalized = []
    used_slugs = set()
    for index, value in enumerate(rows, start=1):
        slug = str(value or "").strip()
        if not slug:
            raise ValueError(f"Slug в home.json под номером {index} пустой")
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError(f"Slug '{slug}' в home.json имеет неверный формат")
        if slug in used_slugs:
            raise ValueError(f"Slug '{slug}' повторяется в home.json")
        if allowed_slugs is not None and slug not in allowed_slugs:
            raise ValueError(f"Slug '{slug}' отсутствует в feed.json")
        used_slugs.add(slug)
        normalized.append(slug)

    return normalized


def parse_home_form(form, feed_rows):
    if "payload" in form and not any(key.startswith("show-") for key in form):
        return normalize_home_slugs(json.loads(form.get("payload", "[]")), allowed_slugs={item["slug"] for item in feed_rows})

    if "home_order" in form:
        allowed_slugs = {item["slug"] for item in feed_rows}
        selected = []
        for slug in form.get("home_order", "").split(","):
            slug = slug.strip()
            if slug and form.get(f"show-{slug}") == "on":
                selected.append(slug)
        return normalize_home_slugs(selected, allowed_slugs=allowed_slugs)

    selected = []
    for item in feed_rows:
        slug = item.get("slug", "")
        if form.get(f"show-{slug}") == "on":
            selected.append((form.get(f"position-{slug}", ""), slug))

    def sort_key(pair):
        value, slug = pair
        try:
            return (0, int(value), slug)
        except (TypeError, ValueError):
            return (1, 0, slug)

    return normalize_home_slugs([slug for _, slug in sorted(selected, key=sort_key)], allowed_slugs={item["slug"] for item in feed_rows})


def build_home_admin_rows(feed_rows, home_slugs):
    order_by_slug = {slug: index + 1 for index, slug in enumerate(home_slugs)}
    return [
        {
            "slug": item["slug"],
            "title": item.get("headline", {}).get("ru", item["slug"]),
            "subline": item.get("subline", {}).get("ru", ""),
            "published": is_published(item),
            "selected": item["slug"] in order_by_slug,
            "position": order_by_slug.get(item["slug"], ""),
        }
        for item in feed_rows
    ]


def build_admin_dashboard(metrics):
    feed = load_json("feed.json")
    home = load_json("home.json")
    collections_data = get_collections()
    collections = collections_data.get("collections", [])
    collection_items_count = sum(len(item.get("items", [])) for item in collections)
    books_count = sum(len(year.get("books", [])) for year in get_books())
    cities_count = len(get_cities())
    peaks_count = len(get_mountain_peaks())
    gpx_count = len(get_gpx_routes())
    published_count = sum(1 for item in feed if is_published(item))
    drafts_count = max(len(feed) - published_count, 0)
    return {
        "stats": [
            {"value": len(feed), "label": "Проектов в ленте", "detail": f"{published_count} опубликовано, {drafts_count} скрыто"},
            {"value": len(home), "label": "Проектов на главной", "detail": "Порядок и видимость"},
            {"value": books_count, "label": "Книг", "detail": "Список прочитанного"},
            {"value": cities_count, "label": "Городов", "detail": "Карточки с фото и координатами"},
            {"value": len(collections), "label": "Коллекций", "detail": f"{collection_items_count} объектов внутри"},
            {"value": peaks_count + gpx_count, "label": "Горных записей", "detail": f"{peaks_count} вершин, {gpx_count} GPX"},
            {"value": metrics.get("cv_downloads", 0), "label": "Скачиваний CV", "detail": "Метрика сайта"},
        ],
        "sections": [
            {"title": "Главная", "description": "Выбор проектов и порядок показа на первом экране.", "url": "/admin/home", "public_url": "/", "primary": "Настроить"},
            {"title": "Проекты", "description": "Лента работ: slug, заголовки, описания, даты и публикация.", "url": "/admin/feed", "public_url": "/", "primary": "Редактировать"},
            {"title": "Книги", "description": "Годы, авторы, названия, обложки и отметка избранного.", "url": "/admin/books", "public_url": "/books", "primary": "Открыть"},
            {"title": "Города", "description": "Карточки городов, изображения, страна и координаты.", "url": "/admin/cities", "public_url": "/cities", "primary": "Управлять"},
            {"title": "Коллекции", "description": "Списки объектов с гибкими свойствами и изображениями.", "url": "/admin/collections", "public_url": "/collections", "primary": "Управлять"},
            {"title": "Горы", "description": "Вершины, статусы восхождений и GPX-маршруты.", "url": "/admin/mountains", "public_url": "/mountains", "primary": "Управлять"},
        ],
    }


def build_feed_items(feed, lang, sort_by_date=True):
    items = []
    for item in feed:
        headline = item["headline"].get(lang, item["headline"].get("ru"))
        image_path = f"/static/img/blog/{item['slug']}/cover.jpg?v={SITE_VERSION}"
        image_file = BASE_DIR / "static" / "img" / "blog" / item["slug"] / "cover.jpg"
        card_path = thumbnail_path(f"img/blog/{item['slug']}/cover.jpg", size=(960, 480))
        items.append(
            {
                "slug": item["slug"],
                "headline": headline,
                "date": format_date(item["date"]),
                "subline": item["subline"].get(lang, item["subline"].get("ru")),
                "image": image_path if image_file.exists() else "",
                "card_image": f"/static/{card_path}?v={SITE_VERSION}" if image_file.exists() else "",
            }
        )
    if sort_by_date:
        items.sort(key=lambda item: parse_date(item["date"]), reverse=True)
    return items


def build_feed(lang):
    feed = get_published_feed()
    return build_feed_items(feed, lang)


def build_home_feed(lang):
    feed_by_slug = {item["slug"]: item for item in get_published_feed()}
    home_slugs = load_json("home.json")
    home_feed = [feed_by_slug[slug] for slug in home_slugs if slug in feed_by_slug]
    return build_feed_items(home_feed, lang, sort_by_date=False)


def get_feed_item(slug, include_unpublished=False):
    feed = load_json("feed.json")
    item = next((entry for entry in feed if entry["slug"] == slug), None)
    if not item:
        return None
    if include_unpublished:
        return item
    return item if is_published(item) else None


def get_preview_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="post-preview")


def make_post_preview_token(slug):
    return get_preview_serializer().dumps({"slug": slug})


def verify_post_preview_token(slug, token):
    if not token:
        return False
    try:
        payload = get_preview_serializer().loads(token, max_age=60 * 60 * 24)
    except (BadSignature, SignatureExpired):
        return False
    return payload.get("slug") == slug


def build_feed_admin_rows(rows):
    admin_rows = []
    for row in rows:
        slug = row.get("slug", "")
        preview_url = f"/{slug}"
        if row.get("published") is False:
            preview_url = f"/{slug}?preview={make_post_preview_token(slug)}"
        admin_rows.append({**row, "preview_url": preview_url})
    return admin_rows


def get_books():
    return load_json("books.json")


def get_metrics():
    path = DATA_DIR / "metrics.json"
    if not path.exists():
        return {"cv_downloads": 0}
    data = load_json("metrics.json")
    if not isinstance(data, dict):
        return {"cv_downloads": 0}
    return {"cv_downloads": int(data.get("cv_downloads", 0) or 0)}


def save_metrics(metrics):
    save_json("metrics.json", metrics)

def increment_cv_downloads():
    with transaction():
        metrics = get_metrics()
        metrics["cv_downloads"] = int(metrics.get("cv_downloads", 0)) + 1
        save_metrics(metrics)


def get_collections():
    return normalize_collections_store(load_json("collections.json"))


def normalize_book_cover(value):
    cover = str(value or "").strip()
    if cover.startswith("/static/img/books/"):
        cover = cover[len("/static/img/books/") :]
    if cover.startswith("img/books/"):
        cover = cover[len("img/books/") :]
    if not cover:
        return ""
    filename = Path(cover).name.strip()
    _, ext = os.path.splitext(filename)
    if not ext:
        return f"{filename}.jpg"
    return filename


def book_cover_asset_path(value):
    filename = normalize_book_cover(value)
    return f"img/books/{filename}" if filename else ""


def flatten_books_rows(books_data):
    rows = []
    for year_block in books_data:
        year = year_block.get("year", "")
        for book in year_block.get("books", []):
            rows.append(
                {
                    "year": year,
                    "author": book.get("author", ""),
                    "title": book.get("title", ""),
                    "cover": normalize_book_cover(book.get("cover", "")),
                    "fav": bool(book.get("fav", False)),
                }
            )
    return rows


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def normalize_book_rows(rows):
    normalized = []
    for index, row in enumerate(rows, start=1):
        year_raw = str(row.get("year", "")).strip()
        author = str(row.get("author", "")).strip()
        title = str(row.get("title", "")).strip()
        cover = normalize_book_cover(row.get("cover", ""))
        fav = parse_bool(row.get("fav", False))

        is_empty = not year_raw and not author and not title and not cover
        if is_empty:
            continue

        if not year_raw:
            raise ValueError(f"Строка {index}: заполните год")
        if not author:
            raise ValueError(f"Строка {index}: заполните автора")
        if not title:
            raise ValueError(f"Строка {index}: заполните название")
        if not cover:
            raise ValueError(f"Строка {index}: заполните обложку")

        try:
            year = int(year_raw)
        except ValueError as exc:
            raise ValueError(f"Строка {index}: год должен быть числом") from exc

        normalized.append(
            {
                "year": year,
                "author": author,
                "title": title,
                "cover": cover,
                "fav": fav,
            }
        )
    return normalized


def group_books_by_year(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["year"], []).append(
            {
                "author": row["author"],
                "title": row["title"],
                "cover": row["cover"],
                "fav": row["fav"],
            }
        )
    return [{"year": year, "books": books} for year, books in grouped.items()]


def books_for_view(books_data):
    years = []
    for year_block in books_data:
        books = []
        for book in year_block.get("books", []):
            books.append(
                {
                    "author": book.get("author", ""),
                    "title": book.get("title", ""),
                    "cover": normalize_book_cover(book.get("cover", "")),
                    "cover_path": book_cover_asset_path(book.get("cover", "")),
                    "fav": bool(book.get("fav", False)),
                }
            )
        years.append({"year": year_block.get("year", ""), "books": books})
    return sorted(years, key=lambda item: int(item.get("year", 0)), reverse=True)


def save_books(books_data):
    save_json("books.json", books_data)


COLLECTION_PROPERTY_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def normalize_collection_cover(value):
    cover = str(value or "").strip()
    if cover.startswith("/static/img/collections/"):
        cover = cover[len("/static/img/collections/") :]
    if cover.startswith("img/collections/"):
        cover = cover[len("img/collections/") :]
    if not cover:
        return ""
    filename = Path(cover).name.strip()
    _, ext = os.path.splitext(filename)
    if not ext:
        return f"{filename}.jpg"
    return filename


def collection_cover_asset_path(value):
    filename = normalize_collection_cover(value)
    return f"img/collections/{filename}" if filename else ""


def slugify_value(value, separator="-"):
    slug = re.sub(r"[^a-z0-9]+", separator, str(value or "").strip().lower())
    slug = re.sub(rf"{re.escape(separator)}+", separator, slug).strip(separator)
    return slug


def normalize_property_key(value):
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not COLLECTION_PROPERTY_KEY_RE.fullmatch(key):
        raise ValueError("Ключ свойства должен содержать только латиницу, цифры и underscore")
    return key


def normalize_collection_property_label(value):
    if isinstance(value, dict):
        labels = {lang: str(value.get(lang, "")).strip() for lang in COLLECTION_LABEL_LANGS}
    else:
        text = str(value or "").strip()
        labels = {lang: text for lang in COLLECTION_LABEL_LANGS}
    return labels


def collection_property_label(prop, lang="ru"):
    label = prop.get("label", "")
    if isinstance(label, dict):
        return str(label.get(lang) or label.get("ru") or label.get("en") or "").strip()
    return str(label or "").strip()


def make_unique_slug(base, used_slugs, fallback_prefix):
    raw = slugify_value(base)
    slug = raw or fallback_prefix
    counter = 2
    while slug in used_slugs:
        slug = f"{raw or fallback_prefix}-{counter}"
        counter += 1
    used_slugs.add(slug)
    return slug


def save_uploaded_collection_images(files):
    saved = []
    paths = []
    COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for uploaded in files:
            if not uploaded or not uploaded.filename:
                continue
            original_name = secure_filename(uploaded.filename)
            extension = Path(original_name).suffix.lower()
            raw = validate_image(uploaded, extension)
            filename = f"{slugify_value(Path(original_name).stem) or 'image'}-{secrets.token_hex(12)}{extension}"
            destination = COLLECTIONS_DIR / filename
            paths.append(destination)
            with destination.open('xb') as handle:
                handle.write(raw)
            if destination.resolve().is_relative_to((BASE_DIR / 'static').resolve()):
                relative = destination.resolve().relative_to((BASE_DIR / 'static').resolve()).as_posix()
                prepared = prepare_thumbnail(relative)
                if prepared != relative:
                    paths.append(BASE_DIR / 'static' / prepared)
            saved.append(filename)
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    if has_request_context():
        g.setdefault('uploaded_paths', []).extend(paths)
    return saved


def normalize_collection_property_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("Свойства коллекции должны быть списком")

    normalized = []
    seen_keys = set()
    used_ids = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Свойство {index}: некорректный формат")

        label = normalize_collection_property_label(row.get("label", ""))
        label_ru = label.get("ru", "")
        label_en = label.get("en", "")
        raw_key = str(row.get("key", "")).strip()
        prop_id = make_unique_slug(row.get("id") or raw_key or label_ru or label_en, used_ids, f"property-{index}")

        is_empty = not label_ru and not label_en and not raw_key
        if is_empty:
            continue

        if not label_ru:
            raise ValueError(f"Свойство {index}: заполните название на русском")
        if not label_en:
            raise ValueError(f"Свойство {index}: заполните название на английском")
        if not raw_key:
            raise ValueError(f"Свойство {index}: заполните key")

        key = normalize_property_key(raw_key)
        if key in seen_keys:
            raise ValueError(f"Свойство {index}: key '{key}' должен быть уникальным")
        seen_keys.add(key)

        normalized.append(
            {
                "id": prop_id,
                "key": key,
                "label": label,
                "type": "text",
            }
        )
    return normalized


def normalize_collection_item_values(values):
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value or "").strip() for key, value in values.items()}


def normalize_collection_image_list(value):
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.splitlines()
    else:
        raw_items = []

    images = []
    seen = set()
    for entry in raw_items:
        filename = normalize_collection_cover(entry)
        if not filename or filename in seen:
            continue
        seen.add(filename)
        images.append(filename)
    return images


def normalize_collection_item_images(row):
    images = normalize_collection_image_list(row.get("images", []))
    image = normalize_collection_cover(row.get("image", ""))
    if image and image not in images:
        images.insert(0, image)
    return images


def legacy_collection_from_row(row, index):
    if not isinstance(row, dict):
        return {
            "id": f"collection-{index}",
            "title": f"Collection {index}",
            "cover_image": "",
            "properties": [],
            "items": [],
        }

    legacy_row = {
        "id": row.get("id") or slugify_value(row.get("title", "")) or f"collection-{index}",
        "title": str(row.get("title", "")).strip() or f"Collection {index}",
        "cover_image": row.get("cover_image") or row.get("cover") or "",
        "properties": row.get("properties") if isinstance(row.get("properties"), list) else [],
        "items": row.get("items") if isinstance(row.get("items"), list) else [],
    }
    for key, value in row.items():
        if key not in legacy_row and key != "cover":
            legacy_row[key] = value
    return legacy_row


def normalize_collection_item_rows(rows, properties, existing_items=None):
    if not isinstance(rows, list):
        raise ValueError("Объекты коллекции должны быть списком")

    property_keys = [prop["key"] for prop in properties]
    existing_map = {item["id"]: item for item in (existing_items or [])}
    normalized = []
    used_ids = set()

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Объект {index}: некорректный формат")

        title = str(row.get("title", "")).strip()
        images = normalize_collection_item_images(row)
        image = images[0] if images else ""
        raw_values = row.get("values", {})
        item_id = make_unique_slug(row.get("id") or title, used_ids, f"item-{index}")

        has_values = isinstance(raw_values, dict) and any(str(value).strip() for value in raw_values.values())
        is_empty = not title and not images and not has_values
        if is_empty:
            continue

        if not title:
            raise ValueError(f"Объект {index}: заполните название")

        existing_values = {}
        if row.get("id") in existing_map:
            existing_values = normalize_collection_item_values(existing_map[row["id"]].get("values", {}))

        values = {key: existing_values[key] for key in existing_values if key not in property_keys}
        incoming_values = normalize_collection_item_values(raw_values)
        for key in property_keys:
            values[key] = incoming_values.get(key, "").strip()

        normalized.append(
            {
                "id": item_id,
                "title": title,
                "image": image,
                "images": images,
                "values": values,
            }
        )
    return normalized


def normalize_collection_record(row, index, used_ids):
    if not isinstance(row, dict):
        raise ValueError(f"Коллекция {index}: некорректный формат")

    title = str(row.get("title", "")).strip()
    if not title:
        raise ValueError(f"Коллекция {index}: заполните название")

    collection_id = make_unique_slug(row.get("id") or title, used_ids, f"collection-{index}")
    properties = normalize_collection_property_rows(row.get("properties", []))
    items = normalize_collection_item_rows(row.get("items", []), properties, row.get("items", []))
    meta = {
        key: value
        for key, value in row.items()
        if key not in {"id", "title", "cover_image", "cover", "properties", "items", "meta"}
    }

    old_meta = row.get("meta", {})
    while isinstance(old_meta, dict):
        meta = {**{key: value for key, value in old_meta.items() if key != "meta"}, **meta}
        old_meta = old_meta.get("meta")

    record = {
        "id": collection_id,
        "title": title,
        "cover_image": normalize_collection_cover(row.get("cover_image") or row.get("cover") or ""),
        "properties": properties,
        "items": items,
    }
    if meta:
        record["meta"] = meta
    return record


def normalize_collections_store(raw_data):
    if isinstance(raw_data, dict):
        source = raw_data.get("collections", [])
    elif isinstance(raw_data, list):
        source = [legacy_collection_from_row(row, index) for index, row in enumerate(raw_data, start=1)]
    else:
        source = []

    used_ids = set()
    collections = [normalize_collection_record(row, index, used_ids) for index, row in enumerate(source, start=1)]
    return {"collections": collections}


def save_collections(collections_data):
    save_json("collections.json", collections_data)


def get_collection_list():
    return get_collections()["collections"]


def get_collection_or_404(collection_id):
    collection = next((item for item in get_collection_list() if item["id"] == collection_id), None)
    if not collection:
        abort(404)
    return collection


def get_collection_item_or_404(collection, item_id):
    item = next((entry for entry in collection.get("items", []) if entry["id"] == item_id), None)
    if not item:
        abort(404)
    return item


def collection_list_view(collections_data):
    items = []
    for item in collections_data:
        cover_image = normalize_collection_cover(item.get("cover_image", ""))
        preview_images = []
        for collection_item in item.get("items", []):
            item_images = collection_item.get("images", [])
            if item_images:
                preview_image = item_images[0]
            else:
                preview_image = collection_item.get("image", "")

            preview_path = collection_cover_asset_path(normalize_collection_cover(preview_image))
            if preview_path:
                preview_images.append(preview_path)

            if len(preview_images) == 4:
                break

        items.append(
            {
                "id": item["id"],
                "title": item.get("title", ""),
                "cover_path": collection_cover_asset_path(cover_image),
                "preview_images": preview_images,
                "properties_count": len(item.get("properties", [])),
                "items_count": len(item.get("items", [])),
            }
        )
    return items


def collection_detail_view(collection, lang="ru"):
    cover_image = normalize_collection_cover(collection.get("cover_image", ""))
    items = []
    for item in collection.get("items", []):
        detail = collection_item_detail_view(collection, item, lang=lang)
        detail["fields_count"] = len(detail["fields"])
        items.append(detail)

    return {
        "id": collection["id"],
        "title": collection.get("title", ""),
        "cover_path": collection_cover_asset_path(cover_image),
        "properties": [
            {
                **prop,
                "label_text": collection_property_label(prop, lang),
                "label_ru": collection_property_label(prop, "ru"),
                "label_en": collection_property_label(prop, "en"),
            }
            for prop in collection.get("properties", [])
        ],
        "items": items,
    }


def collection_item_detail_view(collection, item, lang="ru"):
    item_image = normalize_collection_cover(item.get("image", ""))
    fields = []
    for prop in collection.get("properties", []):
        value = str(item.get("values", {}).get(prop["key"], "")).strip()
        if not value:
            continue
        fields.append({"label": collection_property_label(prop, lang), "key": prop["key"], "value": value})

    return {
        "id": item["id"],
        "title": item.get("title", ""),
        "image_path": collection_cover_asset_path(item_image),
        "gallery": [collection_cover_asset_path(image) for image in normalize_collection_item_images(item)],
        "fields": fields,
    }


def build_collection_form_state(collection=None):
    if collection:
        return {
            "id": collection["id"],
            "title": collection.get("title", ""),
            "cover_image": normalize_collection_cover(collection.get("cover_image", "")),
            "properties": [
                {
                    **prop,
                    "label_ru": collection_property_label(prop, "ru"),
                    "label_en": collection_property_label(prop, "en"),
                }
                for prop in collection.get("properties", [])
            ],
        }
    return {"id": "", "title": "", "cover_image": "", "properties": []}


def build_collection_item_form_state(collection, item=None):
    existing_values = item.get("values", {}) if item else {}
    values = {prop["key"]: str(existing_values.get(prop["key"], "")).strip() for prop in collection.get("properties", [])}
    return {
        "id": item["id"] if item else "",
        "title": item.get("title", "") if item else "",
        "image": normalize_collection_cover(item.get("image", "")) if item else "",
        "images_text": "\n".join(normalize_collection_item_images(item)) if item else "",
        "values": values,
    }


def parse_collection_form_payload(payload, current_collection=None):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Некорректный формат данных коллекции") from exc

    if not isinstance(data, dict):
        raise ValueError("Некорректный формат данных коллекции")

    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("Название коллекции обязательно")

    return {
        "id": current_collection["id"] if current_collection else "",
        "title": title,
        "cover_image": normalize_collection_cover(data.get("cover_image", "")),
        "properties": normalize_collection_property_rows(data.get("properties", [])),
        "items": current_collection.get("items", []) if current_collection else [],
        "meta": current_collection.get("meta", {}) if current_collection else {},
    }


def parse_collection_item_form_payload(payload, collection, current_item=None):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Некорректный формат данных объекта") from exc

    if not isinstance(data, dict):
        raise ValueError("Некорректный формат данных объекта")

    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("Название объекта обязательно")

    incoming_values = data.get("values", {})
    if not isinstance(incoming_values, dict):
        raise ValueError("Некорректный формат значений объекта")

    current_values = normalize_collection_item_values(current_item.get("values", {})) if current_item else {}
    values = {key: value for key, value in current_values.items() if key not in {prop["key"] for prop in collection.get("properties", [])}}
    for prop in collection.get("properties", []):
        values[prop["key"]] = str(incoming_values.get(prop["key"], "")).strip()

    images = normalize_collection_item_images(data)
    if current_item and not images:
        images = normalize_collection_item_images(current_item)

    return {
        "id": current_item["id"] if current_item else "",
        "title": title,
        "image": images[0] if images else "",
        "images": images,
        "values": values,
    }


def merge_collection_item_images(item_payload, uploaded_images):
    if not uploaded_images:
        return item_payload

    images = normalize_collection_image_list(item_payload.get("images", []) + uploaded_images)
    item_payload["images"] = images
    item_payload["image"] = images[0] if images else ""
    return item_payload


def upsert_collection(collections_data, collection_payload, current_collection_id=None):
    collections = collections_data["collections"]
    used_ids = {item["id"] for item in collections if item["id"] != current_collection_id}
    if current_collection_id:
        collection_id = current_collection_id
    else:
        collection_id = make_unique_slug(collection_payload.get("title", ""), used_ids, "collection")

    record = {
        "id": collection_id,
        "title": collection_payload["title"],
        "cover_image": collection_payload["cover_image"],
        "properties": collection_payload["properties"],
        "items": collection_payload["items"],
    }
    if collection_payload.get("meta"):
        record["meta"] = collection_payload["meta"]

    if current_collection_id:
        for index, item in enumerate(collections):
            if item["id"] == current_collection_id:
                collections[index] = record
                break
    else:
        collections.append(record)

    return record


def upsert_collection_item(collections_data, collection_id, item_payload, current_item_id=None):
    collection = next(item for item in collections_data["collections"] if item["id"] == collection_id)
    items = collection["items"]
    used_ids = {item["id"] for item in items if item["id"] != current_item_id}
    if current_item_id:
        item_id = current_item_id
    else:
        item_id = make_unique_slug(item_payload.get("title", ""), used_ids, "item")

    record = {
        "id": item_id,
        "title": item_payload["title"],
        "image": item_payload["image"],
        "images": item_payload["images"],
        "values": item_payload["values"],
    }

    if current_item_id:
        for index, item in enumerate(items):
            if item["id"] == current_item_id:
                items[index] = record
                break
    else:
        items.append(record)

    return record


def is_admin_authenticated():
    if current_app.config.get("DEV_ADMIN_LOGIN") is True:
        return True
    return session.get("admin_logged_in", False) is True


def get_admin_totp_secret():
    return re.sub(r"\s+", "", ADMIN_TOTP_SECRET).upper()


def generate_totp_code(secret, timestamp=None, interval=TOTP_INTERVAL_SECONDS, digits=TOTP_DIGITS):
    normalized_secret = re.sub(r"\s+", "", secret).upper()
    if not normalized_secret:
        return None

    try:
        key = base64.b32decode(normalized_secret, casefold=True)
    except binascii.Error:
        return None

    current_time = int(timestamp if timestamp is not None else time.time())
    counter = current_time // interval
    counter_bytes = struct.pack(">Q", counter)
    digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code = truncated % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp_code(secret, code, allowed_drift=1):
    normalized_code = re.sub(r"\s+", "", code)
    if not re.fullmatch(rf"\d{{{TOTP_DIGITS}}}", normalized_code):
        return False

    now = int(time.time())
    for drift in range(-allowed_drift, allowed_drift + 1):
        candidate = generate_totp_code(
            secret,
            timestamp=now + drift * TOTP_INTERVAL_SECONDS,
        )
        if candidate and secrets.compare_digest(candidate, normalized_code):
            return True
    return False


def is_safe_next_path(path):
    return isinstance(path, str) and path.startswith("/") and not path.startswith("//")


def register_routes(app):
    @app.context_processor
    def inject_seo_defaults():
        translations = get_translations()
        lang = get_lang(translations)
        base_url = request.url_root.rstrip("/")
        canonical_url = build_url(base_url, request.path, lang)
        alternate_urls = {
            code: build_url(base_url, request.path, code) for code in SUPPORTED_LANGS
        }
        return {
            "site_url": base_url,
            "canonical_url": canonical_url,
            "alternate_urls": alternate_urls,
            "site_version": SITE_VERSION,
            "analytics_enabled": current_app.config["APP_ENV"] == "production" and not request.path.startswith("/admin"),
            "asset_url": lambda filename: url_for("static", filename=filename, v=SITE_VERSION),
            "thumbnail_url": lambda filename: url_for("static", filename=thumbnail_path(filename), v=SITE_VERSION),
            "absolute_url": lambda value: urljoin(base_url + "/", value),
            "supported_langs": SUPPORTED_LANGS,
            "collection_property_label": collection_property_label,
        }

    @app.get("/")
    def home():
        translations = get_translations()
        lang = get_lang(translations)
        feed = build_home_feed(lang)
        return render_template(
            "pages/home.html",
            t=translations[lang],
            lang=lang,
            feed=feed,
            breadcrumbs=[{"name": translations[lang]["site"]["title"], "url": "/"}],
        )

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if is_admin_authenticated():
            return redirect(url_for("admin_panel"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""
        next_path = request.args.get("next", session.get("admin_next_path", "/admin"))
        awaiting_2fa = session.get("admin_2fa_pending", False) is True
        totp_secret = get_admin_totp_secret()

        if request.method == "POST":
            stage = request.form.get("stage", "password")
            next_path = request.form.get("next", "/admin")
            safe_next_path = next_path if is_safe_next_path(next_path) else "/admin"

            if stage == "password":
                password = request.form.get("password", "")

                if not ADMIN_PASSWORD or ADMIN_PASSWORD == "admin" or not secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")):
                    session.pop("admin_2fa_pending", None)
                    session.pop("admin_next_path", None)
                    error = "Неверный пароль"
                elif not totp_secret:
                    error = "2FA не настроен: добавьте ADMIN_TOTP_SECRET в переменные окружения."
                elif generate_totp_code(totp_secret) is None:
                    error = "ADMIN_TOTP_SECRET имеет неверный формат."
                else:
                    session["admin_2fa_pending"] = True
                    session["admin_2fa_started"] = time.time()
                    session["admin_next_path"] = safe_next_path
                    awaiting_2fa = True
                    next_path = safe_next_path
            elif stage == "totp":
                awaiting_2fa = session.get("admin_2fa_pending", False) is True
                safe_next_path = session.get("admin_next_path", safe_next_path)
                next_path = safe_next_path

                if not awaiting_2fa or time.time() - session.get("admin_2fa_started", 0) > 300:
                    error = "Сначала введите пароль."
                else:
                    totp_code = request.form.get("totp_code", "")
                    if verify_totp_code(totp_secret, totp_code):
                        session.pop("admin_2fa_pending", None)
                        session.pop("admin_next_path", None)
                        session.clear()
                        session["admin_logged_in"] = True
                        session.permanent = True
                        session["csrf_token"] = secrets.token_urlsafe(32)
                        return redirect(safe_next_path if is_safe_next_path(safe_next_path) else url_for("admin_panel"))

                    error = "Неверный код из Authenticator."
            else:
                error = "Неизвестный этап авторизации."

        return render_template(
            "admin/admin-login.html",
            t=translations[lang],
            lang=lang,
            title="Вход в админку",
            description="Вход в административную панель сайта",
            robots="noindex,nofollow",
            error=error,
            next_path=next_path if is_safe_next_path(next_path) else "/admin",
            awaiting_2fa=awaiting_2fa,
        )

    @app.get("/admin")
    def admin_panel():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin"))

        translations = get_translations()
        lang = get_lang(translations)
        metrics = get_metrics()
        dashboard = build_admin_dashboard(metrics)
        return render_template(
            "admin/admin.html",
            t=translations[lang],
            lang=lang,
            title="Админка",
            description="Контентный дашборд сайта",
            robots="noindex,nofollow",
            metrics=metrics,
            dashboard=dashboard,
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
            ],
        )

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("admin_logged_in", None)
        session.pop("admin_2fa_pending", None)
        session.pop("admin_next_path", None)
        return redirect(url_for("admin_login"))

    @app.route("/admin/books", methods=["GET", "POST"])
    def admin_books():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/books"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""

        if request.method == "POST":
            payload = request.form.get("payload", "[]")
            try:
                rows = json.loads(payload)
                if not isinstance(rows, list):
                    raise ValueError("Некорректный формат данных")
                normalized_rows = normalize_book_rows(rows)
                save_books(group_books_by_year(normalized_rows))
                return redirect(url_for("admin_books", saved=1))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                error = str(exc)

        rows = flatten_books_rows(get_books())
        saved = request.args.get("saved") == "1"
        return render_template(
            "admin/admin-books.html",
            t=translations[lang],
            lang=lang,
            title="Редактор книг",
            description="Редактирование books.json",
            robots="noindex,nofollow",
            rows=rows,
            error=error,
            saved=saved,
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Books", "url": "/admin/books"},
            ],
        )

    @app.route("/admin/feed", methods=["GET", "POST"])
    def admin_feed():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/feed"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""

        if request.method == "POST":
            try:
                rows = parse_feed_form(request.form)
                save_json("feed.json", rows)
                return redirect(url_for("admin_feed", saved=1))
            except (ValueError, TypeError) as exc:
                error = str(exc)

        saved = request.args.get("saved") == "1"
        return render_template(
            "admin/admin-feed.html",
            t=translations[lang],
            lang=lang,
            title="Редактор feed",
            description="Управление лентой проектов",
            robots="noindex,nofollow",
            rows=build_feed_admin_rows(load_json("feed.json")),
            error=error,
            saved=saved,
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Feed", "url": "/admin/feed"},
            ],
        )

    @app.route("/admin/home", methods=["GET", "POST"])
    def admin_home():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/home"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""
        feed_rows = load_json("feed.json")

        if request.method == "POST":
            try:
                rows = parse_home_form(request.form, feed_rows)
                save_json("home.json", rows)
                return redirect(url_for("admin_home", saved=1))
            except (ValueError, TypeError) as exc:
                error = str(exc)

        saved = request.args.get("saved") == "1"
        home_slugs = load_json("home.json")
        return render_template(
            "admin/admin-home.html",
            t=translations[lang],
            lang=lang,
            title="Редактор home",
            description="Управление проектами на главной",
            robots="noindex,nofollow",
            rows=build_home_admin_rows(feed_rows, home_slugs),
            error=error,
            saved=saved,
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Home", "url": "/admin/home"},
            ],
        )

    @app.get("/admin/cities")
    def admin_cities():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/cities"))

        translations = get_translations()
        lang = get_lang(translations)
        return render_template(
            "admin/admin-cities.html",
            t=translations[lang],
            lang=lang,
            title="Cities",
            description="Управление cities.json",
            robots="noindex,nofollow",
            cities=build_admin_city_rows(get_cities()),
            message=request.args.get("message", ""),
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Cities", "url": "/admin/cities"},
            ],
        )

    @app.route("/admin/mountains", methods=["GET", "POST"])
    def admin_mountains():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/mountains"))

        error = ""
        message = request.args.get("message", "")

        if request.method == "POST":
            action = request.form.get("action", "")
            try:
                if action == "add-peak":
                    peaks = get_mountain_peaks()
                    peaks.append(parse_peak_form(request.form))
                    save_mountain_peaks(peaks)
                    return redirect(url_for("admin_mountains", message="peak-created"))
                if action == "upload-gpx":
                    save_uploaded_gpx(request.files.get("gpx_file"))
                    return redirect(url_for("admin_mountains", message="gpx-uploaded"))
                raise ValueError("Неизвестное действие")
            except ValueError as exc:
                error = str(exc)

        translations = get_translations()
        lang = get_lang(translations)
        return render_template(
            "admin/admin-mountains.html",
            t=translations[lang],
            lang=lang,
            title="Горная активность",
            description="Управление вершинами и GPX-маршрутами",
            robots="noindex,nofollow",
            error=error,
            message=message,
            peaks=get_mountain_peaks(),
            gpx_routes=get_gpx_routes(),
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Горная активность", "url": "/admin/mountains"},
            ],
        )

    @app.post("/admin/mountains/peaks/<peak_id>/delete")
    def admin_mountain_peak_delete(peak_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/mountains"))
        save_mountain_peaks([peak for peak in get_mountain_peaks() if peak["id"] != peak_id])
        return redirect(url_for("admin_mountains", message="peak-deleted"))

    @app.post("/admin/mountains/gpx/<route_id>/delete")
    def admin_mountain_gpx_delete(route_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/mountains"))
        filename = f"{secure_filename(route_id)}.gpx"
        (GPX_ROUTES_DIR / filename).unlink(missing_ok=True)
        return redirect(url_for("admin_mountains", message="gpx-deleted"))

    @app.route("/admin/cities/new", methods=["GET", "POST"])
    def admin_city_new():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/cities/new"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""
        city = build_city_form_state()

        if request.method == "POST":
            try:
                cities = get_cities()
                city_payload = parse_city_form(request.form)
                if any(item["slug"] == city_payload["slug"] for item in cities):
                    raise ValueError("Slug должен быть уникальным")
                CITIES_DIR.joinpath(city_payload["slug"]).mkdir(parents=True, exist_ok=True)
                save_uploaded_city_images(request.files.getlist("photos"), city_payload["slug"], require_one=True)
                cities.append(city_payload)
                try:
                    save_cities(cities)
                except Exception:
                    for path in g.get("uploaded_paths", []):
                        path.unlink(missing_ok=True)
                    raise
                g.uploads_committed = True
                return redirect(url_for("admin_cities", message="created"))
            except ValueError as exc:
                error = str(exc)
                city = {
                    "name": request.form.get("name", ""),
                    "name_en": request.form.get("name_en", ""),
                    "country": request.form.get("country", ""),
                    "country_en": request.form.get("country_en", ""),
                    "slug": request.form.get("slug", ""),
                    "location": request.form.get("location", ""),
                }

        return render_template(
            "admin/admin-city-form.html",
            t=translations[lang],
            lang=lang,
            title="Новый город",
            description="Создание города",
            robots="noindex,nofollow",
            city=city,
            error=error,
            form_mode="create",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Cities", "url": "/admin/cities"},
                {"name": "Новый город", "url": "/admin/cities/new"},
            ],
        )

    @app.route("/admin/cities/<city_slug>/edit", methods=["GET", "POST"])
    def admin_city_edit(city_slug):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next=f"/admin/cities/{city_slug}/edit"))

        translations = get_translations()
        lang = get_lang(translations)
        cities = get_cities()
        current_city = next((city for city in cities if city["slug"] == city_slug), None)
        if not current_city:
            abort(404)

        error = ""
        city = build_city_form_state(current_city)

        if request.method == "POST":
            try:
                city_payload = parse_city_form(request.form)
                if any(item["slug"] == city_payload["slug"] and item["slug"] != city_slug for item in cities):
                    raise ValueError("Slug должен быть уникальным")
                if any(upload and upload.filename for upload in request.files.getlist("photos")):
                    CITIES_DIR.joinpath(city_payload["slug"]).mkdir(parents=True, exist_ok=True)
                    save_uploaded_city_images(request.files.getlist("photos"), city_payload["slug"])
                for index, item in enumerate(cities):
                    if item["slug"] == city_slug:
                        cities[index] = city_payload
                        break
                try:
                    save_cities(cities)
                except Exception:
                    for path in g.get("uploaded_paths", []):
                        path.unlink(missing_ok=True)
                    raise
                g.uploads_committed = True
                return redirect(url_for("admin_cities", message="updated"))
            except ValueError as exc:
                error = str(exc)
                city = {
                    "name": request.form.get("name", ""),
                    "name_en": request.form.get("name_en", ""),
                    "country": request.form.get("country", ""),
                    "country_en": request.form.get("country_en", ""),
                    "slug": request.form.get("slug", ""),
                    "location": request.form.get("location", ""),
                }

        return render_template(
            "admin/admin-city-form.html",
            t=translations[lang],
            lang=lang,
            title=f"Редактировать {current_city['name']}",
            description="Редактирование города",
            robots="noindex,nofollow",
            city=city,
            error=error,
            form_mode="edit",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Cities", "url": "/admin/cities"},
                {"name": current_city["name"], "url": f"/admin/cities/{city_slug}/edit"},
            ],
        )

    @app.post("/admin/cities/<city_slug>/delete")
    def admin_city_delete(city_slug):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/cities"))

        cities = get_cities()
        save_cities([city for city in cities if city["slug"] != city_slug])
        return redirect(url_for("admin_cities", message="deleted"))

    @app.get("/admin/collections")
    def admin_collections():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/collections"))

        translations = get_translations()
        lang = get_lang(translations)
        return render_template(
            "admin/admin-collections.html",
            t=translations[lang],
            lang=lang,
            title="Коллекции",
            description="Управление коллекциями",
            robots="noindex,nofollow",
            collections=collection_list_view(get_collection_list()),
            message=request.args.get("message", ""),
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Collections", "url": "/admin/collections"},
            ],
        )

    @app.route("/admin/collections/new", methods=["GET", "POST"])
    def admin_collection_new():
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/collections/new"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""
        form_state = build_collection_form_state()

        if request.method == "POST":
            payload = request.form.get("payload", "{}")
            try:
                collections_data = get_collections()
                collection_payload = parse_collection_form_payload(payload)
                collection = upsert_collection(collections_data, collection_payload)
                save_collections(collections_data)
                return redirect(url_for("admin_collection_detail", collection_id=collection["id"], message="created"))
            except (ValueError, TypeError) as exc:
                error = str(exc)
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        form_state = {
                            "id": "",
                            "title": str(parsed.get("title", "")).strip(),
                            "cover_image": normalize_collection_cover(parsed.get("cover_image", "")),
                            "properties": parsed.get("properties", []),
                        }
                except json.JSONDecodeError:
                    pass

        return render_template(
            "admin/admin-collections-form.html",
            t=translations[lang],
            lang=lang,
            title="Новая коллекция",
            description="Создание коллекции",
            robots="noindex,nofollow",
            collection=form_state,
            error=error,
            form_mode="create",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Collections", "url": "/admin/collections"},
                {"name": "Новая коллекция", "url": "/admin/collections/new"},
            ],
        )

    @app.route("/admin/collections/<collection_id>/edit", methods=["GET", "POST"])
    def admin_collection_edit(collection_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next=f"/admin/collections/{collection_id}/edit"))

        translations = get_translations()
        lang = get_lang(translations)
        error = ""
        collection = get_collection_or_404(collection_id)
        form_state = build_collection_form_state(collection)

        if request.method == "POST":
            payload = request.form.get("payload", "{}")
            try:
                collections_data = get_collections()
                current_collection = next(item for item in collections_data["collections"] if item["id"] == collection_id)
                collection_payload = parse_collection_form_payload(payload, current_collection=current_collection)
                collection = upsert_collection(collections_data, collection_payload, current_collection_id=collection_id)
                save_collections(collections_data)
                return redirect(url_for("admin_collection_detail", collection_id=collection["id"], message="updated"))
            except (ValueError, TypeError) as exc:
                error = str(exc)
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        form_state = {
                            "id": collection_id,
                            "title": str(parsed.get("title", "")).strip(),
                            "cover_image": normalize_collection_cover(parsed.get("cover_image", "")),
                            "properties": parsed.get("properties", []),
                        }
                except json.JSONDecodeError:
                    pass

        return render_template(
            "admin/admin-collections-form.html",
            t=translations[lang],
            lang=lang,
            title=f"Редактировать {collection['title']}",
            description="Редактирование коллекции",
            robots="noindex,nofollow",
            collection=form_state,
            error=error,
            form_mode="edit",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Collections", "url": "/admin/collections"},
                {"name": collection["title"], "url": f"/admin/collections/{collection_id}"},
                {"name": "Редактирование", "url": f"/admin/collections/{collection_id}/edit"},
            ],
        )

    @app.get("/admin/collections/<collection_id>")
    def admin_collection_detail(collection_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next=f"/admin/collections/{collection_id}"))

        translations = get_translations()
        lang = get_lang(translations)
        collection = get_collection_or_404(collection_id)
        return render_template(
            "admin/admin-collection-detail.html",
            t=translations[lang],
            lang=lang,
            title=collection["title"],
            description="Управление коллекцией",
            robots="noindex,nofollow",
            collection=collection_detail_view(collection, lang=lang),
            message=request.args.get("message", ""),
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Collections", "url": "/admin/collections"},
                {"name": collection["title"], "url": f"/admin/collections/{collection_id}"},
            ],
        )

    @app.post("/admin/collections/<collection_id>/delete")
    def admin_collection_delete(collection_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next="/admin/collections"))

        collections_data = get_collections()
        collections = collections_data["collections"]
        collections_data["collections"] = [item for item in collections if item["id"] != collection_id]
        save_collections(collections_data)
        return redirect(url_for("admin_collections", message="deleted"))

    @app.route("/admin/collections/<collection_id>/items/new", methods=["GET", "POST"])
    def admin_collection_item_new(collection_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next=f"/admin/collections/{collection_id}/items/new"))

        translations = get_translations()
        lang = get_lang(translations)
        collection = get_collection_or_404(collection_id)
        error = ""
        form_state = build_collection_item_form_state(collection)

        if request.method == "POST":
            payload = request.form.get("payload", "{}")
            try:
                collections_data = get_collections()
                current_collection = next(item for item in collections_data["collections"] if item["id"] == collection_id)
                item_payload = parse_collection_item_form_payload(payload, current_collection)
                uploaded_images = save_uploaded_collection_images(request.files.getlist("photos"))
                item_payload = merge_collection_item_images(item_payload, uploaded_images)
                item = upsert_collection_item(collections_data, collection_id, item_payload)
                save_collections(collections_data)
                g.uploads_committed = True
                return redirect(url_for("admin_collection_detail", collection_id=collection_id, message="item-created"))
            except (ValueError, TypeError) as exc:
                error = str(exc)
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        form_state = {
                            "id": "",
                            "title": str(parsed.get("title", "")).strip(),
                            "image": normalize_collection_cover(parsed.get("image", "")),
                            "images_text": "\n".join(normalize_collection_item_images(parsed)),
                            "values": parsed.get("values", {}),
                        }
                except json.JSONDecodeError:
                    pass

        return render_template(
            "admin/admin-collection-item-form.html",
            t=translations[lang],
            lang=lang,
            title=f"Новый объект: {collection['title']}",
            description="Создание объекта коллекции",
            robots="noindex,nofollow",
            collection=collection,
            item=form_state,
            error=error,
            form_mode="create",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Collections", "url": "/admin/collections"},
                {"name": collection["title"], "url": f"/admin/collections/{collection_id}"},
                {"name": "Новый объект", "url": f"/admin/collections/{collection_id}/items/new"},
            ],
        )

    @app.route("/admin/collections/<collection_id>/items/<item_id>/edit", methods=["GET", "POST"])
    def admin_collection_item_edit(collection_id, item_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next=f"/admin/collections/{collection_id}/items/{item_id}/edit"))

        translations = get_translations()
        lang = get_lang(translations)
        collection = get_collection_or_404(collection_id)
        current_item = get_collection_item_or_404(collection, item_id)
        error = ""
        form_state = build_collection_item_form_state(collection, current_item)

        if request.method == "POST":
            payload = request.form.get("payload", "{}")
            try:
                collections_data = get_collections()
                current_collection = next(item for item in collections_data["collections"] if item["id"] == collection_id)
                item_record = next(entry for entry in current_collection["items"] if entry["id"] == item_id)
                item_payload = parse_collection_item_form_payload(payload, current_collection, current_item=item_record)
                uploaded_images = save_uploaded_collection_images(request.files.getlist("photos"))
                item_payload = merge_collection_item_images(item_payload, uploaded_images)
                upsert_collection_item(collections_data, collection_id, item_payload, current_item_id=item_id)
                save_collections(collections_data)
                g.uploads_committed = True
                return redirect(url_for("admin_collection_detail", collection_id=collection_id, message="item-updated"))
            except (ValueError, TypeError) as exc:
                error = str(exc)
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        form_state = {
                            "id": item_id,
                            "title": str(parsed.get("title", "")).strip(),
                            "image": normalize_collection_cover(parsed.get("image", "")),
                            "images_text": "\n".join(normalize_collection_item_images(parsed)),
                            "values": parsed.get("values", {}),
                        }
                except json.JSONDecodeError:
                    pass

        return render_template(
            "admin/admin-collection-item-form.html",
            t=translations[lang],
            lang=lang,
            title=f"Редактировать объект: {current_item['title']}",
            description="Редактирование объекта коллекции",
            robots="noindex,nofollow",
            collection=collection,
            item=form_state,
            error=error,
            form_mode="edit",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Админка", "url": "/admin"},
                {"name": "Collections", "url": "/admin/collections"},
                {"name": collection["title"], "url": f"/admin/collections/{collection_id}"},
                {"name": current_item["title"], "url": f"/admin/collections/{collection_id}/items/{item_id}/edit"},
            ],
        )

    @app.post("/admin/collections/<collection_id>/items/<item_id>/delete")
    def admin_collection_item_delete(collection_id, item_id):
        if not is_admin_authenticated():
            return redirect(url_for("admin_login", next=f"/admin/collections/{collection_id}"))

        collections_data = get_collections()
        collection = next((item for item in collections_data["collections"] if item["id"] == collection_id), None)
        if not collection:
            abort(404)
        collection["items"] = [item for item in collection["items"] if item["id"] != item_id]
        save_collections(collections_data)
        return redirect(url_for("admin_collection_detail", collection_id=collection_id, message="item-deleted"))

    @app.get("/about")
    def about():
        translations = get_translations()
        lang = get_lang(translations)
        file_path = find_content_file(PAGES_DIR / "about", lang)
        if not file_path:
            abort(404)
        meta, html = load_markdown(file_path)
        return render_template(
            "pages/article.html",
            t=translations[lang],
            lang=lang,
            title=meta.get("title", ""),
            description=meta.get("description", ""),
            image=resolve_cover("", meta),
            content=html,
            page_type="article",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": meta.get("title", "About"), "url": "/about"},
            ],
        )

    @app.get("/cv")
    def cv():
        translations = get_translations()
        lang = get_lang(translations)
        # Сначала ищем CV по стандартному паттерну страниц проекта: cv-ru.md / cv.ru.md и т.д.
        file_path = find_content_file(PAGES_DIR / "cv", lang)
        if not file_path:
            abort(404)
        meta, html = load_markdown(file_path)
        return render_template(
            "pages/cv.html",
            t=translations[lang],
            lang=lang,
            title=meta.get("title", "CV"),
            description=meta.get("description", "CV"),
            content=html,
            download_url=url_for("cv_download"),
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "CV", "url": "/cv"},
            ],
        )

    @app.get("/cv/download")
    def cv_download():
        if not CV_PDF_PATH.exists():
            abort(404)
        if request.method == "GET":
            increment_cv_downloads()
        return send_file(CV_PDF_PATH, as_attachment=True, download_name=CV_PDF_PATH.name)

    @app.get("/cities")
    def cities():
        translations = get_translations()
        lang = get_lang(translations)
        cities_data = get_cities()
        return render_template(
            "pages/cities.html",
            t=translations[lang],
            lang=lang,
            body_class="city-service",
            page_class="cities-page",
            country_groups=build_city_groups(cities_data, lang),
            title=f"{translations[lang]['labels']['cities']} | {translations[lang]['site']['title']}",
            description=f"{translations[lang]['labels']['cities']} — {translations[lang]['site']['description']}",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": translations[lang]["labels"]["cities"], "url": "/cities"},
            ],
        )

    @app.get("/api/cities/<city_slug>")
    def city_data(city_slug):
        cities_data = get_cities()
        city_item = next((c for c in cities_data if c["slug"] == city_slug), None)
        if not city_item:
            abort(404)
        return jsonify(
            {
                "slug": city_item["slug"],
                "name": city_item["name"],
                "country": city_item["country"],
                "gallery": build_city_gallery(city_slug),
            }
        )

    @app.get("/books")
    def books():
        translations = get_translations()
        lang = get_lang(translations)
        return render_template(
            "pages/books.html",
            t=translations[lang],
            lang=lang,
            years=books_for_view(get_books()),
            title=f"Books | {translations[lang]['site']['title']}",
            description="Books list",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Books", "url": "/books"},
            ],
        )

    @app.get("/collections")
    def collections():
        translations = get_translations()
        lang = get_lang(translations)
        return render_template(
            "pages/collections.html",
            t=translations[lang],
            lang=lang,
            collections=collection_list_view(get_collection_list()),
            title=f"Collections | {translations[lang]['site']['title']}",
            description="Collections list",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Collections", "url": "/collections"},
            ],
        )

    @app.get("/collections/<collection_id>")
    def collection(collection_id):
        translations = get_translations()
        lang = get_lang(translations)
        collection = get_collection_or_404(collection_id)
        return render_template(
            "pages/collection.html",
            t=translations[lang],
            lang=lang,
            collection=collection_detail_view(collection, lang=lang),
            initial_item_id=None,
            title=f"{collection['title']} | Collections",
            description=collection["title"],
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Collections", "url": "/collections"},
                {"name": collection["title"], "url": f"/collections/{collection_id}"},
            ],
        )

    @app.get("/collections/<collection_id>/<item_id>")
    def collection_item(collection_id, item_id):
        translations = get_translations()
        lang = get_lang(translations)
        collection = get_collection_or_404(collection_id)
        item = get_collection_item_or_404(collection, item_id)
        return render_template(
            "pages/collection.html",
            t=translations[lang],
            lang=lang,
            collection=collection_detail_view(collection, lang=lang),
            initial_item_id=item["id"],
            title=f"{item['title']} | {collection['title']}",
            description=item["title"],
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Collections", "url": "/collections"},
                {"name": collection["title"], "url": f"/collections/{collection_id}"},
                {"name": item["title"], "url": f"/collections/{collection_id}/{item_id}"},
            ],
        )

    @app.get("/mountains")
    def mountains():
        translations = get_translations()
        lang = get_lang(translations)
        return render_template(
            "pages/mountains.html",
            t=translations[lang],
            lang=lang,
            body_class="mountains-service",
            title=f"Горы | {translations[lang]['site']['title']}",
            description="Карта покорённых вершин и GPX-маршрутов",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": "Горы", "url": "/mountains"},
            ],
        )

    @app.get("/api/mountains")
    def mountains_data():
        peaks = [peak for peak in get_mountain_peaks() if peak["isSummited"]]
        routes_payload = []
        for route_item in get_gpx_routes():
            routes_payload.append({
                "id": route_item.get("id"),
                "name": route_item.get("name"),
                "uploadedAt": route_item.get("uploadedAt"),
                "bounds": route_item.get("bounds"),
                "geojson": route_item.get("geojson", {"type": "FeatureCollection", "features": []}),
            })
        return jsonify({"peaks": peaks, "routes": routes_payload})

    @app.get("/cities/<city_slug>")
    def city(city_slug):
        translations = get_translations()
        lang = get_lang(translations)
        cities_data = get_cities()
        city_item = next((c for c in cities_data if c["slug"] == city_slug), None)
        if not city_item:
            abort(404)
        gallery = build_city_gallery(city_slug)
        return render_template(
            "pages/city.html",
            t=translations[lang],
            lang=lang,
            city={
                "slug": city_item["slug"],
                "name": city_item["name"],
                "country": city_item["country"],
            },
            gallery=gallery,
            total=len(gallery),
            title=f"{city_item['name']} | {translations[lang]['labels']['cities']}",
            description=f"{city_item['name']}, {city_item['country']}",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": translations[lang]["labels"]["cities"], "url": "/cities"},
                {"name": city_item["name"], "url": f"/cities/{city_slug}"},
            ],
        )

    @app.get("/<slug>")
    def article(slug):
        translations = get_translations()
        lang = get_lang(translations)
        post_path = find_content_file(POSTS_DIR / slug, lang)
        page_path = find_content_file(PAGES_DIR / slug, lang)

        if post_path:
            feed_item_raw = get_feed_item(slug, include_unpublished=True)
            can_preview = verify_post_preview_token(slug, request.args.get("preview", ""))
            if not feed_item_raw or (not is_published(feed_item_raw) and not can_preview):
                abort(404)

        file_path = post_path or page_path
        if not file_path:
            abort(404)
        meta, html = load_markdown(file_path)
        feed_item = get_feed_item(slug, include_unpublished=True) if post_path else get_feed_item(slug)
        headline = feed_item.get("headline", {}) if feed_item else {}
        article_title = meta.get("title") or headline.get(lang) or headline.get("ru") or slug
        description = meta.get("description", "")
        if not description and feed_item:
            description = feed_item["subline"].get(lang, feed_item["subline"].get("ru", ""))
        return render_template(
            "pages/article.html",
            t=translations[lang],
            lang=lang,
            title=article_title,
            display_title=meta.get("title", ""),
            description=description,
            image=resolve_cover(slug, meta),
            content=html,
            page_type="article",
            published_time=format_date_iso(feed_item["date"]) if feed_item else "",
            breadcrumbs=[
                {"name": translations[lang]["site"]["title"], "url": "/"},
                {"name": article_title, "url": f"/{slug}"},
            ],
        )

    @app.get("/translations.json")
    def translations():
        response = jsonify(get_translations())
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/search.json")
    def search_index():
        feed = get_published_feed()
        index = []
        for item in feed:
            entry = {
                "slug": item["slug"],
                "headline": item["headline"],
                "date": format_date(item["date"]),
                "subline": item["subline"],
                "content": {},
            }
            for lang in SUPPORTED_LANGS:
                file_path = POSTS_DIR / f"{item['slug']}-{lang}.md"
                if not file_path.exists():
                    file_path = POSTS_DIR / f"{item['slug']}.{lang}.md"
                if not file_path.exists():
                    continue
                _, html = load_markdown(file_path)
                entry["content"][lang] = strip_html(html)
            index.append(entry)
        response = jsonify(index)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/robots.txt")
    def robots():
        base_url = request.url_root.rstrip("/")
        content = "\n".join(
            [
                "User-agent: *",
                "Allow: /",
                f"Sitemap: {base_url}/sitemap.xml",
            ]
        )
        response = make_response(content)
        response.mimetype = "text/plain"
        return response

    @app.get("/sitemap.xml")
    def sitemap():
        base_url = request.url_root.rstrip("/")
        feed = get_published_feed()
        cities = get_cities()
        collections = get_collection_list()
        static_paths = ["/", "/cv", "/about", "/cities", "/books", "/products", "/collections"]
        post_paths = [f"/{item['slug']}" for item in feed]
        city_paths = [f"/cities/{item['slug']}" for item in cities]
        collection_paths = [f"/collections/{item['id']}" for item in collections]
        collection_item_paths = [
            f"/collections/{collection['id']}/{item['id']}"
            for collection in collections
            for item in collection.get("items", [])
        ]
        all_paths = static_paths + post_paths + city_paths + collection_paths + collection_item_paths
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for path in all_paths:
            for lang in SUPPORTED_LANGS:
                lines.append("  <url>")
                lines.append(f"    <loc>{build_url(base_url, path, lang)}</loc>")
                lines.append("  </url>")
        lines.append("</urlset>")
        response = make_response("\n".join(lines))
        response.mimetype = "application/xml"
        return response

    @app.errorhandler(404)
    def not_found(error):
        translations = get_translations()
        lang = get_lang(translations)
        response = make_response(
            render_template(
                "pages/404.html",
                t=translations[lang],
                lang=lang,
                title=translations[lang]["errors"]["not_found"],
                robots="noindex, nofollow",
            ),
            404,
        )
        return response
