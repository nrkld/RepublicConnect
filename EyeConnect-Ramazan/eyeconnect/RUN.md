# EyeConnect — запуск на ноутбуке (с экраном)

Рекомендуется Python 3.11 (mediapipe без wheels под 3.13), venv.

1. Проверка без камеры: `python -m eyeconnect.test_smoke` → SMOKE OK
2. Проверка камеры+трекинга: `python -m eyeconnect.main --mode preview` — сядь в 60см от камеры, Q — выход
3. Калибровка взглядом: `python -m eyeconnect.main --mode calibrate` — смотри на 126 точек (~4 мин)
4. Курсор взглядом: `python -m eyeconnect.main --mode cursor` — крестик за взглядом.
   С кликом: `--click --click-dwell 1200`. Без системного курсора: `--no-syscursor`.
5. Логи: `%USERPROFILE%\.eyeconnect\*.csv + *.json`, профиль: `%USERPROFILE%\.eyeconnect\gaze.npz`
   Кадр проверки: `python -m eyeconnect.webcam_check --frames 150`

На Pi (64-bit OS): `sudo apt install libgl1 libglib2.0-0`, `pip install -r eyeconnect/requirements-pi.txt`, дальше те же команды.

Приватность: gaze-логи — медданные, не коммить (*.csv в .gitignore).
