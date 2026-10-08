# fatikhov

## Локальный запуск

Выполните команды из корня проекта (`public_html`). Нужен установленный Python 3.

cd /Users/ruslanfatihov/Desktop/Projects/RuslanFatikhov/public_html
source .venv/bin/activate
python app.py

Сайт будет доступен по адресу http://127.0.0.1:5044. Режим отладки выключен. Для локальной разработки его можно включить командой `FLASK_DEBUG=1 python app.py`.

Чтобы локально заходить в админку без пароля:

```bash
DEV_ADMIN_LOGIN=1 python app.py
```

Флаг работает только вместе с `APP_ENV=development`, который `python app.py` выставляет автоматически. На сервере не задавайте `DEV_ADMIN_LOGIN`.

Для повторного запуска после установки зависимостей:

```bash
source .venv/bin/activate
python app.py
```

Остановить сервер: `Ctrl+C`. Выйти из виртуального окружения: `deactivate`.

На macOS, если при создании окружения появляется окно «python3 Not Opened», закройте его кнопкой `Done` и создайте новое окружение системным Python (из корня проекта):

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Используйте новое `.venv`: старое окружение `venv`, перенесённое вместе с проектом, может содержать файлы с меткой карантина macOS.

## Local config

The app reads local environment variables from `.env` in the project root.

## Deploy to Timeweb (no venv)

Use local dependency directory `pydeps` and WSGI entrypoint from project root.

```bash
cd /home/c/cc91451/RuslanFatikhov/public_html
python3.10 -m pip install --target ./pydeps -r requirements.txt
find pydeps -type d -exec chmod 755 {} \;
find pydeps -type f -exec chmod 644 {} \;
chmod 644 index.wsgi .htaccess
```

After upload/update files, reload the site in Timeweb panel.

## Настройки безопасности и обновление

- Установите зависимости из обновлённого `requirements.txt` (добавлен Pillow).
- Задайте `ADMIN_PASSWORD` и `ADMIN_TOTP_SECRET` в окружении или `.env`. Без них вход закрыт; пароль `admin` запрещён. Пароль и TOTP проверяются с общим лимитом: 10 запросов с одного IP и 30 для учётной записи за 15 минут. Оба этапа учитываются, этап 2FA действует 5 минут.
- `SECRET_KEY` — минимум 32 случайных символа. Если он не задан, приложение создаёт случайный постоянный ключ `data/.session-secret` с правами 600. Сохраняйте его между перезапусками и не копируйте между независимыми сайтами. Старый стандартный ключ больше не принимается.
- WSGI по умолчанию требует HTTPS; cookie имеет Secure, HttpOnly и SameSite=Lax. `python app.py` включает локальный HTTP-режим. Для других локальных способов запуска явно задавайте `APP_ENV=development`; на сервере этого значения быть не должно.
- Proxy-заголовки по умолчанию игнорируются. Если TLS завершается на доверенном прокси, задайте `TRUSTED_PROXY_HOPS` равным числу доверенных прокси только при условии, что они удаляют входные X-Forwarded-* заголовки. X-Forwarded-Host не используется. Рекомендуется задать `TRUSTED_HOSTS` списком фактических доменов через запятую.
- Загрузите новую `.htaccess`: существование файла больше не даёт публичного доступа. Для другого веб-сервера повторите разрешающий список: публичны только статические изображения/CSS/JS и маршруты Flask. Каталоги data, content, окружения, исходники и логи должны быть закрыты.
- PDF резюме перемещён из `static/files/cv.pdf` в `data/cv.pdf`. При обновлении удалите старую публичную копию; старый URL перенаправляется в маршрут со счётчиком. Markdown Qook Easy переименован в `qook-easy-ru.md`; публикационный статус не изменён.
- Процесс приложения должен иметь права записи в `data` и `static/img/thumbnails`. Блокировки рассчитаны на локальную файловую систему Unix; для нескольких серверов нужен общий транзакционный источник данных.
- До появления переведённых страниц публично доступен только русский язык. Существующие поля переводов в данных сохранены.
- Публичные GET только читают подготовленные миниатюры. Команда подготовки и правила обновления описаны ниже; оригиналы доступны в галерее.

Проверка исправлений: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v`.


## Производительность и подготовка ресурсов

Перед использованием новых изображений, добавленных вручную, выполните:

```bash
.venv/bin/python scripts/prepare_images.py
```

Команда создаёт WebP обложек опубликованных постов (вписывание в 960×480 без обрезки), одну обложку на город и миниатюры книг/коллекций. `--galleries` дополнительно обрабатывает все фотографии городов. Оригиналы не изменяются. Загрузка через админку сразу подготавливает миниатюру вне транзакции; при конфликте revision новые файлы удаляются. При отсутствии производного файла сайт использует оригинал. Ключ миниатюры учитывает размер и mtime исходника: после копирования исходников с новыми временными метками повторите подготовку.

Inter 4.1 хранится в `static/fonts` (400, 500, 600, 700, normal); лицензия SIL OFL — `static/fonts/LICENSE.txt`. Источник: https://github.com/rsms/inter/releases/tag/v4.1. CDN шрифтов не используется.

Карты используют общий загрузчик `static/js/maplibre-openfreemap.js`: MapLibre GL JS и стиль OpenFreeMap Liberty (`https://tiles.openfreemap.org/styles/liberty`). Токен не нужен. При ошибке сети список городов остаётся доступным, карта показывает сообщение.

Горная карта читает вершины из `data/mountain_peaks.gpx` (`wpt`) и маршруты из всех файлов `data/gpx_routes/*.gpx`. Для добавления маршрута можно просто положить GPX-файл в эту папку или загрузить его через `/admin/mountains`.

`APP_ENV=development` отключает Метрику и долгий cache. В production Метрика включена только на публичных страницах после события load, в свободное время браузера. Apache `.htaccess` и Flask задают годовой Cache-Control только для `/static/…?v=…`; без версии используется no-cache. При изменении CSS/JS увеличивайте `SITE_VERSION` в `routes.py`. Уже открытые страницы не перезагружаются.

Проверки и воспроизводимые замеры:

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/frontend.test.cjs
.venv/bin/python scripts/benchmark.py
.venv/bin/python scripts/benchmark_contention.py
.venv/bin/python scripts/benchmark_http.py http://127.0.0.1:5044
```

`benchmark.py` измеряет Flask test client; `benchmark_http.py` — HTTP TTFB через curl; `benchmark_contention.py` — ответ публичных страниц во время 200-мс админ-запроса. Это не браузерные FCP/LCP. Подробные результаты — `PERFORMANCE-REPORT.md`.
