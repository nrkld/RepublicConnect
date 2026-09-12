"""Hybrid cursor-core (Фаза 1): общий слой EyeConnect + MagnetCursor.

- config: пресеты MOUSE/GAZE.
- providers: Gaze/Mouse/Auto провайдеры указателя.
- clicks: DwellClicker + ClickRouter (клики в снапнутой точке).
- win_cursor: единственный владелец системного курсора.
- snap_core: канонический магнит-снап (Target/MagnetSnap).
- profiles: единый ~/.eyeconnect_hybrid с чтением legacy-профилей.

Только stdlib. Старые проекты делегируют сюда, если hybrid на sys.path,
иначе работают локально (поведение не меняется).
"""
__version__ = "0.1.0"
