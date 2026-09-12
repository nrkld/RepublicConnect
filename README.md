# RepublicConnect

Low-cost AI-система управления компьютером взглядом + магнитный курсор для Windows.
Низкобюджетная альтернатива дорогим ай-трекерам (Tobii и т.п.): обычная webcam + Raspberry Pi / ноутбук + Python.

Репозиторий-зонт над тремя модулями:

- **`EyeConnect-Ramazan/`** — gaze-трекер + gaze-курсор. Веб-камера → FaceMesh/iris → калибровка 126 точек → курсор взглядом.
- **`magnetcursor/`** — магнитный курсор для Windows. Курсор прилипает к кликабельному (кнопки, ссылки, меню) через UI Automation, с гистерезисом и детектом вырывания.
- **`hybrid/`** — общий слой: провайдер координат (мышь/взгляд) → магнит-снап → один `set_pos`, клики в снапнутой точке. Только stdlib + ctypes, без камеры/UIA в импортах.

Презентация и документация лежат **в этом же репо** — ничего не потеряно.

> EN short: webcam gaze control + magnetic snapping cursor for Windows. Gaze provider (EyeConnect) → magnet snap (MagnetCursor core) → single system cursor owner (`hybrid`). Python 3.11, Windows-first, Pi-supported.

---

## Состав репозитория (ВСЁ в одном месте)

```text
RepublicConnect/
├── README.md                        ← этот файл
├── LICENSE                          ← MIT (дубль EyeConnect-Ramazan/LICENSE)
├── opencode.json                    ← конфиг OpenCode (LSP ruff/pyright, MCP, форматтер)
├── pyproject.toml                   ← общая гигиена ruff для 3 проектов (Python 3.11)
├── requirements-hybrid.txt          ← единый install для hybrid (Windows)
├── .gitignore                       ← корень (кэш/логи/профили НЕ коммитим)
│
├── EyeConnect-Ramazan/              ← gaze-трекер и курсор
│   ├── eyeconnect/                  ← код (main, gaze/, ui/, eval/)
│   │   ├── RUN.md                   ← запуск на ноутбуке
│   │   ├── CALIBRATION.md           ← рисерч калибровки + аудит + roadmap
│   │   ├── requirements.txt / requirements-pi.txt
│   ├── docs/opencode-sessions/*.md  ← логи opencode-сессий (5 шт.)
│   ├── third_party/                 ← вендоренные EyeTrax, L2CS-Net, face-detection (RetinaFace)
│   ├── pyproject.toml, README.md, LICENSE, .gitignore
│   └── *.docx                       ← доп. документ
│
├── magnetcursor/                    ← магнитный курсор (Windows UIA)
│   ├── magnetcursor/ (targets.py, snap.py, overlay.py, service.py, config.py, handcheck.py)
│   ├── tests/, requirements.txt, README.md, .gitignore
│
├── hybrid/                          ← курсор-ядро (stdlib-only)
│   ├── __main__.py / engine.py / providers.py / snap_core.py
│   ├── clicks.py / win_cursor.py / profiles.py / config.py
│   ├── tests/, README.md
│
├── *.pptx                           ← презентация проекта (2 файла: рабочий + backup)
│   ├── EyeConnect-Razrabotka-i-validaciya-....pptx.pptx
│   └── EyeConnect-pptx-backup.pptx
```

Вендоренные зависимости (`third_party/`) тоже закоммичены, т.к. RetinaFace нет на PyPI — ставится из `EyeConnect-Ramazan/third_party/face-detection/`.

Конфиг OpenCode (`opencode.json`) закоммичен намеренно: LSP (pyright/ruff), форматтер, MCP-серверы (playwright, filesystem, fetch, memory, sequential-thinking, gh_grep, github, context7).

---

## Требования

- Windows 10/11 (магнит и системный курсор — только `win32`; gaze-часть работает и на Pi).
- Python **3.11** (важно: у mediapipe нет wheels под 3.13).
- Веб-камера для gaze-режимов. Без камеры работают: `--check`, `--probe` (частично), `test_smoke`, mouse-режимы.
- Raspberry Pi: 64-bit OS + `eyeconnect/requirements-pi.txt` + `sudo apt install libgl1 libglib2.0-0`.

---

## Быстрый старт

### 0. Установка (Windows, из корня репо)

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-hybrid.txt
rem RetinaFace отдельно (нет на PyPI):
pip install -e EyeConnect-Ramazan\third_party\face-detection
```

Проверка без камеры/UIA:

```bat
python -m hybrid --check
python -m eyeconnect.test_smoke
rem из EyeConnect-Ramazan: SMOKE OK
```

### 1. EyeConnect — взгляд → курсор

Запуск из `EyeConnect-Ramazan/`:

```bat
cd EyeConnect-Ramazan
python -m eyeconnect.test_smoke
python -m eyeconnect.main --mode preview
python -m eyeconnect.main --mode calibrate
python -m eyeconnect.main --mode cursor --click --click-dwell 1200
python -m eyeconnect.webcam_check --frames 150
```

Режимы `eyeconnect.main`:

| Режим | Что делает |
|---|---|
| `preview` | проверка камеры и ирисов, Q — выход |
| `calibrate` | калибровка 126 точек serpentine (~4 мин, settle 0.8с) |
| `cursor [--click]` | полноэкранный курсор + опциональный dwell-клик и системный курсор Windows (`--no-syscursor` — без системного) |
| `webcam_check` | диагностика `det N/M + fps`, сейв в `~/.eyeconnect/webcam_check.jpg` |

Подробно: `EyeConnect-Ramazan/eyeconnect/RUN.md`.

### 2. MagnetCursor — магнит к кликабельному

```bat
pip install -r magnetcursor\requirements.txt
python -m magnetcursor
```

Откроется окно **MagnetCursor** (поверх остальных): статус ON/OFF, счётчик целей, кнопки Включить/Выключить/Выход.
Горячие клавиши: `F9` — вкл/выкл, `F12` — выход.

Как работает:

1. `targets.py` — собирает интерактивные элементы активного окна + ярлыки рабочего стола через Windows UI Automation (кэш в фоне). Строгий режим (`MAGNET_STRICT`, по умолчанию вкл): только кнопки/ссылки/меню/табы/чекбоксы; `--no-strict` — всё кликабельное. Z-order проверка отбрасывает перекрытые окна; при смене фокуса кэш сбрасывается.
2. `snap.py` — жёсткий снап в центр цели с гистерезисом (`MAGNET_CAPTURE` войти / `MAGNET_RELEASE` выйти), детект вырывания (рывок/тяга прочь) + cooldown.
3. `overlay.py` — зелёная рамка поверх всех окон (click-through).
4. `handcheck.py` — `python -m magnetcursor.handcheck`: детектор промахов по курсору-руке, пишет где магнит слеп.

Настройки (`magnetcursor/magnetcursor/config.py`): `MAGNET_CAPTURE / MAGNET_RELEASE / MAGNET_FLICK_PX / MAGNET_COOLDOWN`.

Браузеры: Chrome/Edge показывают ссылки только с флагом `--force-renderer-accessibility` (дописать в ярлык после `.exe`). Firefox — сразу.

### 3. Hybrid — gaze + мышь + магнит в одном цикле

Запуск **из корня** `RepublicConnect/` (чтобы находился `import hybrid`):

```bat
python -m hybrid --check
python -m hybrid --probe
python -m hybrid --migrate
python -m hybrid --source auto
python -m hybrid --source gaze --no-magnet
```

Частые флаги: `--seconds N`, `--fps 120`, `--tracker unigaze|l2cs|facemesh`, `--camera 0`, `--no-dwell / --dwell-s 1.2`, `--no-wink-click`, `--strict / --no-strict`, `--recalib / --no-calib`. Выход — `F12`, `F9` — вкл/выкл.

Архитектура по модулям:

- `config` — пресеты `MOUSE` (20/35) / `GAZE` (120/180): capture/release/flick/cooldown/away_frames. Взгляду нужны большие радиусы (точность 1–2°), мыши — малые.
- `snap_core` — канон магнита (`Target`/`MagnetSnap`, гистерезис + вырывание); `magnetcursor/snap.py` делегирует сюда.
- `win_cursor` — единственный владелец системного курсора (`get/set/do_click/pressed/screen_size`).
- `providers` — `PointerSample`, `GazeProvider` (гейты потери лица/саккад/jump + EMA), `MouseProvider`, `AutoProvider` (мышь ведёт с cooldown, иначе gaze/hold), `AsyncGaze` (инференс в фоне + `_predict`).
- `clicks` — `DwellClicker` (фиксация → клик) + `ClickRouter` (wink по фронту + dwell только по снапу + cooldown).
- `engine` — главный цикл `run_loop` (provider → snap → `set_pos`, клики, оверлей, `F9/F12`), `build_provider`, `needs_calibration`, `pick_compute_device`.
- `profiles` — пути и миграция профилей (см. ниже).
- `__main__` — CLI: `--check / --migrate / --probe / --source`.

Подробно: `hybrid/README.md`.

---

## Калибровка (126 точек, RidgeCV, settle)

Полный разбор: `EyeConnect-Ramazan/eyeconnect/CALIBRATION.md`. Кратко:

- Ориентиры точности: 2D-mapping ≤2°, appearance-based без калибровки 3–3.7° (ETH-XGaze 3.7°, MPIIGaze 3.4°), webcam-калиброванная ~1–1.4° (GazeFollower 1.05°, Kaduk 2024 1.4°/1.1°).
- 126 равноудалённых точек serpentine (~4 мин): serpentine/rectangular лучше circular/random (длинные саккады вредят).
- Что починили относительно первой версии: `Ridge(alpha=1.0)` → `RidgeCV(0.1,1,10)` + `fit_robust` (сброс худшей точки при residual>2.5·median + refit); `mean(buf)` → robust-mean (медиана+MAD); row-major → serpentine; добавлен settle 0.8с + резка саккад (`is_saccade thr=0.25`); валидация train-fit → + LOO (честная оценка) с вердиктом OK/СРЕДНЕ/ПЛОХО; сырые сэмплы сохраняются в `gaze_samples_*.npz`.
- Конфиг: `CALIB_SETTLE_S=0.8`, `RIDGE_ALPHAS=(0.1,1,10)`, `CALIB_RANSAC=True`, `VALID_MAX_DEG=2.0`, `HEAD_SHIFT_THR=0.15`.
- Roadmap калибровки: drift-коррекция (4 угла+центр), weightedRidge по dwell-кликам, blink→click через EAR → PCA контура + анизотропная нормализация → smooth-pursuit → GP/fine-tune (RPi5+).

---

## Профили, логи, приватность

- EyeConnect: `~/.eyeconnect/gaze.npz + gaze_meta.json`, логи `~/.eyeconnect/*.csv + *.json`, кадр `webcam_check.jpg`.
- Hybrid: рабочий каталог `~/.eyeconnect_hybrid/` (`gaze.npz`, `gaze_meta.json`). `resolve_*` сначала смотрит гибрид, потом legacy `~/.eyeconnect/` (только читает). Миграция: `python -m hybrid --migrate`. Без профиля gaze-источники требуют калибровки.
- MagnetCursor: `~/.magnetcursor/`.
- Gaze-логи — медданные, хранятся локально открытым текстом: **не коммитить** (`*.csv`, `*.npz` в `.gitignore`), при передаче — шифровать.
- В репо сознательно НЕ лежат: `*.csv`, `*.npz`, `webcam_check.jpg`, `.venv/`, кэши (`__pycache__/`, `.pytest_cache/`, `.ruff_cache/`). Презентации, доки, сессии, `opencode.json` — лежат.

---

## Документация в репо

- `EyeConnect-Ramazan/eyeconnect/RUN.md` — запуск MVP на ноутбуке/Pi.
- `EyeConnect-Ramazan/eyeconnect/CALIBRATION.md` — наука, аудит, улучшения, roadmap.
- `EyeConnect-Ramazan/docs/opencode-sessions/*.md` — 5 логов opencode-сессий (`cosmic-river`, `kind-engine`, `mighty-river`, `mighty-star`, `sunny-knight`).
- `*.pptx` (2 шт.) — презентация «Разработка и валидация низкобюджетной AI-системы управления компьютером…» + backup. Открывать в PowerPoint.
- `EyeConnect-Ramazan/eyeconnect/data/README.txt` — про словари.
- `hybrid/README.md`, `magnetcursor/README.md`, `EyeConnect-Ramazan/README.md` — README подмодулей (не удалять, здесь — зонт).
- `EyeConnect-Ramazan/third_party/*/VENDORED_FROM.txt` + `LICENSE.*` — откуда взято вендоренное.

---

## OpenCode-конфиг (`opencode.json`)

Закоммичен как часть проекта. Что внутри:

- LSP: `pyright` + `ruff` (абсолютные пути под Python 3.11 на Windows).
- Formatter: `ruff format $FILE`.
- MCP: `playwright` (local, вкл), `gh_grep` (remote, вкл), `filesystem` (local, вкл — разрешены корень репо + `~/.eyeconnect`), `fetch` (local, вкл), `memory` (local, вкл), `sequential-thinking` (local, вкл), `github` (local, выкл — нужен `GITHUB_TOKEN`), `context7` (remote, выкл — нужен `CONTEXT7_API_KEY`).
- Permissions: `skill.*: allow`.

> При переносе на другую машину поправь абсолютные пути (`C:\Users\nisno\...`, `C:\Program Files\nodejs\npx.cmd`) под своё окружение. Переменные окружения: `{env:CONTEXT7_API_KEY}`, `{env:GITHUB_TOKEN}`.

---

## Разработка и тесты

```bat
pytest
python -m hybrid --check
python -m eyeconnect.test_smoke
ruff check .
ruff format .
```

- Корневой `pyproject.toml` фиксирует ruff-правила (`F401,B023,UP,SIM102,RUF059,I001`; `BLE001,S110,S112` — осознанно не селектим: широкие except в рантайме камеры/UIA/COM — принятый стиль). Код проектов под них не правится.
- `hybrid/tests/`, `magnetcursor/tests/` — тесты подмодулей.
- `requirements-hybrid.txt` собран из `magnetcursor/requirements.txt` + `eyeconnect/requirements.txt` (дубли убраны, добавлен `pytest`; Pi-зависимости не тянуть).

---

## Лицензия

MIT — см. `LICENSE` (корень) и `EyeConnect-Ramazan/LICENSE`.
Вендоренные компоненты имеют свои лицензии: `third_party/*/LICENSE.*-MIT`.

---

## Roadmap

- [ ] Drift-коррекция и weightedRidge по dwell-кликам (Фаза 2)
- [ ] Blink→click через EAR, head-shift варнинг
- [ ] PCA контура + анизотропная нормализация, smooth-pursuit опция (Фаза 3)
- [ ] GP-регрессор / fine-tune ETH-XGaze (Фаза 4, RPi5+)
- [ ] Улучшить `handcheck` покрытие и авто-тюнинг `MAGNET_*` под gaze-пресеты
- [ ] CI: `pytest + ruff` на Windows + smoke без камеры
