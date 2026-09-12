"""Настройки MagnetCursor."""
from pathlib import Path

# STRICT: липнуть только к настоящим контролам (кнопки/ссылки/меню/табы/чеки).
# Текст, картинки, кастом и списки/деревья обычных окон отбрасываются
# (в VSCode/браузерах они раздают кликабельные паттерны кому попало).
# Ярлыки рабочего стола (ListItem) оставляем всегда.
MAGNET_STRICT = True

# Радиус захвата/отпускания в px (гистерезис против дребезга между соседями)
MAGNET_CAPTURE = 20.0
MAGNET_RELEASE = 35.0
# Рывок сильнее — мгновенно отпустить; пауза перед повторным захватом, с
MAGNET_FLICK_PX = 45.0
MAGNET_COOLDOWN = 0.6

PROFILE_DIR = Path.home() / ".magnetcursor"
PROFILE_DIR.mkdir(exist_ok=True)
