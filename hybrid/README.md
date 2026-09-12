# hybrid — общий слой EyeConnect + MagnetCursor

Курсор-ядро: провайдер координат (мышь/взгляд) → магнит-снап → один `set_pos`,
клики — в снапнутой точке. Только stdlib + ctypes, без камеры/UIA в импортах.
Запуск из корня `Ramazan/` (чтобы находился `import hybrid`).

## Запуск

```bat
python -m hybrid --check                  :: самопроверка без камеры/UIA
python -m hybrid --probe                  :: живое окружение: мышь + eyeconnect/камера
python -m hybrid --source auto            :: гибридный цикл (взгляд+мышь+магнит)
python -m hybrid --source gaze --no-magnet :: чистый gaze-курсор без снапа
```

Частые флаги: `--seconds N`, `--fps 120`, `--tracker unigaze|l2cs|facemesh`,
`--camera 0`, `--no-dwell` / `--dwell-s 1.2`, `--no-wink-click`,
`--strict` / `--no-strict`, `--recalib` / `--no-calib`. Выход — `F12`, `F9` — вкл/выкл.

## Архитектура по модулям

- `config` — пресеты `MOUSE` (20/35) / `GAZE` (120/180): capture/release/flick/cooldown/away_frames.
- `snap_core` — канон магнита (`Target`/`MagnetSnap`, гистерезис + вырывание); `magnetcursor/snap.py` делегирует сюда.
- `win_cursor` — единственный владелец системного курсора (`get/set/do_click/pressed/screen_size`, `set_sys_cursor` — alias).
- `providers` — `PointerSample`, `GazeProvider` (гейты потери лица/саккад/jump + EMA), `MouseProvider`, `AutoProvider` (мышь ведёт с cooldown, иначе gaze/hold), `AsyncGaze` (инференс в фоне + `_predict`).
- `clicks` — `DwellClicker` (фиксация → клик) + `ClickRouter` (wink по фронту + dwell только по снапу + cooldown).
- `engine` — главный цикл `run_loop` (provider → snap → `set_pos`, клики, оверлей, `F9/F12`), `build_provider`, `needs_calibration`, `pick_compute_device`.
- `profiles` — пути и миграция профилей (см. ниже).
- `kb_targets` — цели dwell-клавиатуры (`keyboard_targets*`, геометрия 1-в-1 с `DwellKeyboard`).
- `__main__` — CLI: `--check` / `--migrate` / `--probe` / `--source`.

## Профили

Рабочий каталог — `~/.eyeconnect_hybrid/` (`gaze.npz`, `gaze_meta.json`).
`resolve_*` сначала смотрит гибрид, потом legacy `~/.eyeconnect/` (не удаляем, только читаем).
`python -m hybrid --migrate` — скопировать legacy в гибрид. Без профиля gaze-источники требуют калибровки.
