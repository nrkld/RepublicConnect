# EyeConnect — gaze-курсор

Low-cost gaze cursor control via webcam + Raspberry Pi for people with severe motor impairments.

- `preview` — проверка камеры и ирисов
- `calibrate` — калибровка 126 точек (~4 мин)
- `cursor [--click]` — полноэкранный курсор + опциональный dwell-клик и системный курсор Windows
- `webcam_check` — диагностика `det N/M + fps`, сейв в `~/.eyeconnect/webcam_check.jpg`

Подробно: `eyeconnect/RUN.md`. Код: `eyeconnect/`.
Профиль: `~/.eyeconnect/gaze.npz + gaze_meta.json`. Логи: `~/.eyeconnect/*.csv + *.json` (не коммитить).

Требования: Python 3.11, `pip install -r eyeconnect/requirements.txt` (Pi: `requirements-pi.txt`, 64-bit OS).
Тест без камеры: `python -m eyeconnect.test_smoke` → `SMOKE OK`.

Лицензия: MIT. Медданные: gaze-логи хранятся локально открытым текстом — шифруйте при передаче.
