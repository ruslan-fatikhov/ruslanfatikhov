"""Prepare public derivatives offline; never modifies source images."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image_utils import STATIC_DIR, prepare_thumbnail
from routes import get_published_feed, get_cities, list_city_images


def prepare(galleries=False):
    records = []
    sources = [(f"img/blog/{row['slug']}/cover.jpg", (960, 480)) for row in get_published_feed()]
    for city in get_cities():
        images = [name for name in list_city_images(city['slug']) if '_thumbnail' not in name]
        sources.extend((f"img/cities/{city['slug']}/{name}", (640, 640)) for name in (images if galleries else images[:1]))
    # Collections use thumbnails in public templates as well.
    for folder in ('collections', 'books'):
        sources.extend((path.relative_to(STATIC_DIR).as_posix(), (640, 640)) for path in (STATIC_DIR / 'img' / folder).glob('*') if path.is_file())
    for source, size in sources:
        if not (STATIC_DIR / source).is_file():
            continue
        target = prepare_thumbnail(source, size)
        if target == source:
            raise RuntimeError(f'Could not prepare {source}')
        records.append((source, target, (STATIC_DIR / source).stat().st_size, (STATIC_DIR / target).stat().st_size))
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--galleries', action='store_true', help='Also prepare all city gallery photos (default: one cover per city)')
    args = parser.parse_args()
    for source, target, before, after in prepare(args.galleries):
        print(f'{source}\t{target}\t{before}\t{after}')
