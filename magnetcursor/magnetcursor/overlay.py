"""Подсветка цели магнита поверх всех окон (рамка). Click-through: клики проходят сквозь.

tkinter + WinAPI (WS_EX_TRANSPARENT). Если tkinter недоступен — NullOverlay.
"""
import queue
import threading

try:
    import tkinter as tk
    _HAS_TK = True
except Exception:
    tk = None
    _HAS_TK = False

# HWND наших оверлеев — targets.py пропускает их при проверке z-порядка,
# иначе WindowFromPoint всегда упирался бы в нашу же подсветку.
OVERLAY_HWNDS = set()

# Стиль прогресса dwell — в стиле зелёной рамки цели.
PROGRESS_COLOR = "#00ff00"
PROGRESS_WIDTH = 3
PROGRESS_RADIUS = 14


def _draw_progress(cv, x, y, frac):
    """Нарисовать дугу прогресса dwell вокруг (x, y) на канвасе cv.

    frac: 0..1. frac is None, frac <= 0 или frac >= 1 — стереть дугу.
    Тег дуги — "progress", рамка цели его не задевает (стирается отдельно).
    Вызывать только из Tk-потока (tick).
    """
    try:
        cv.delete("progress")
    except Exception:
        pass
    try:
        if x is None or y is None or frac is None:
            return
        f = float(frac)
        if not 0.0 < f < 1.0:
            return
        px, py = int(x), int(y)
        r = PROGRESS_RADIUS
        cv.create_arc(px - r, py - r, px + r, py + r,
                      start=90, extent=-360.0 * f, style="arc",
                      outline=PROGRESS_COLOR, width=PROGRESS_WIDTH,
                      tags="progress")
    except Exception:
        pass


class Overlay:
    _QMAX = 64

    def __init__(self):
        self._q = queue.Queue(maxsize=self._QMAX)
        self._out = queue.Queue()  # действия из окна: 'toggle' / 'quit'
        self._thread = None

    def start(self):
        if self._thread is None and _HAS_TK:
            try:
                while True:
                    self._q.get_nowait()
            except queue.Empty:
                pass
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def poll_action(self):
        """Забрать действие из окна (не блокирует)."""
        try:
            kind, _ = self._out.get_nowait()
            return kind
        except queue.Empty:
            return None
        except Exception:
            return None

    def set_target(self, rect):
        """rect = (left, top, right, bottom) или None. Не блокирует."""
        try:
            self._q.put_nowait(("TARGET", rect))
        except Exception:
            pass

    def set_state(self, on):
        """Вкл/выкл магнит — обновить окно-статус. Не блокирует."""
        try:
            self._q.put_nowait(("STATE", bool(on)))
        except Exception:
            pass

    def set_count(self, n):
        """Сколько целей видит магнит. Не блокирует (троттлить снаружи)."""
        try:
            self._q.put_nowait(("COUNT", int(n)))
        except Exception:
            pass

    def set_progress(self, x, y, frac):
        """Прогресс dwell-фиксации вокруг (x, y). Не блокирует.

        frac 0..1 — дуга; frac >= 1 или None (или x/y None) — стереть.
        """
        try:
            self._q.put_nowait(("PROGRESS", (x, y, frac)))
        except Exception:
            pass

    def stop(self):
        try:
            try:
                while True:
                    self._q.get_nowait()
            except queue.Empty:
                pass
            self._q.put_nowait(("STOP", None))
        except Exception:
            pass
        # дождаться teardown Tk в его потоке, иначе гонка и Tcl_AsyncDelete на выходе
        th = self._thread
        if th is not None and th.is_alive():
            try:
                th.join(timeout=2.0)
            except Exception:
                pass
        self._thread = None

    def _run(self):
        import ctypes
        try:
            prev_fg = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            prev_fg = 0
        # NoDefaultRoot: не регистрировать корень в tkinter-глобалях,
        # иначе teardown из чужого потока даёт Tcl_AsyncDelete на выходе.
        # Внимание: в CPython 3.11 tk.NoDefaultRoot() — обычная функция
        # (не контекстный менеджер): ставит _support_default_root=False и
        # удаляет _default_root. Контекстный протокол у неё отсутствует,
        # поэтому просто вызываем и НЕ восстанавливаем флаг — иначе
        # глобаль _default_root указывала бы на интерпретатор Tk-потока.
        try:
            tk.NoDefaultRoot()
        except Exception:
            pass
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", "magenta")
        root.configure(bg="magenta")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{sw}x{sh}+0+0")
        cv = tk.Canvas(root, width=sw, height=sh, bg="magenta",
                       highlightthickness=0, bd=0)
        cv.pack()
        # click-through; hwnd сохраняем сразу — после destroy winfo_id() мёртв
        saved_hwnd = None
        try:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            GWL_EX = -20
            WS_LAYERED, WS_TRANSPARENT = 0x80000, 0x20
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EX)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EX, ex | WS_LAYERED | WS_TRANSPARENT)
            saved_hwnd = int(hwnd)
            OVERLAY_HWNDS.add(saved_hwnd)
        except Exception:
            pass
        cur = None
        magnet_on = True
        count = 0

        # --- обычное окно управления: сворачивается, кнопки, подсказки ---
        st = tk.Toplevel(root)
        st.title("MagnetCursor")
        st.resizable(False, False)
        st.configure(bg="#1c1c1c")
        st.geometry(f"264x214+{sw - 274}+{sh - 264}")
        st.protocol("WM_DELETE_WINDOW", st.iconify)  # крестик = свернуть, не выход
        try:
            st.focusmodel("passive")  # сами фокус не просим
        except Exception:
            pass
        lbl_state = tk.Label(st, text="MAGNET  ON", fg="#00ff88", bg="#1c1c1c",
                             font=("Segoe UI", 13, "bold"))
        lbl_state.pack(pady=(10, 0))
        lbl_count = tk.Label(st, text="целей: 0", fg="#cccccc", bg="#1c1c1c",
                             font=("Segoe UI", 10))
        lbl_count.pack()
        btn_toggle = tk.Button(st, text="Выключить (F9)", width=22,
                               command=lambda: self._out.put_nowait(("toggle", None)))
        btn_toggle.pack(pady=(8, 4))
        tk.Button(st, text="Выход (F12)", width=22,
                  command=lambda: self._out.put_nowait(("quit", None))).pack()
        tk.Label(st, text="F9 — вкл/выкл   F12 — выход", fg="#888888",
                 bg="#1c1c1c", font=("Segoe UI", 9)).pack(pady=(8, 4))
        saved_st_hwnd = None
        try:
            st_hwnd = int(ctypes.windll.user32.GetParent(st.winfo_id()))
            saved_st_hwnd = st_hwnd
            OVERLAY_HWNDS.add(st_hwnd)
            st.attributes("-topmost", True)
            st.deiconify()
            st.update_idletasks()
            # вернуть фокус туда, где был пользователь (окно показали без спроса)
            if prev_fg:
                try:
                    ctypes.windll.user32.SetForegroundWindow(prev_fg)
                except Exception:
                    pass
        except Exception:
            try:
                st.deiconify()
            except Exception:
                pass

        def refresh_status():
            lbl_state.config(
                text="MAGNET  ON" if magnet_on else "MAGNET  OFF",
                fg="#00ff88" if magnet_on else "#ff5555")
            lbl_count.config(text=f"целей: {count}")
            try:
                btn_toggle.config(text="Выключить (F9)" if magnet_on else "Включить (F9)")
            except Exception:
                pass

        after_id = None
        stopping = False

        def tick():
            nonlocal cur, magnet_on, count, after_id, stopping
            while True:
                try:
                    kind, val = self._q.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    continue
                try:
                    if kind == "STOP":
                        stopping = True
                        # очередь переиспользуется между стартами — слить хвост,
                        # чтобы старые TARGET не всплыли при следующем start()
                        try:
                            while True:
                                self._q.get_nowait()
                        except queue.Empty:
                            pass
                        # выйти из mainloop, destroy — только после (иначе
                        # Tcl_AsyncDelete: интерпретатор нельзя рвать из хендлера)
                        try:
                            root.quit()
                        except Exception:
                            pass
                        return
                    if kind == "TARGET":
                        if val != cur:
                            l, t, r, b = [int(v) for v in val] if val is not None else (None,) * 4
                            cur = val
                            cv.delete("all")
                            if cur is not None:
                                cv.create_rectangle(l - 3, t - 3, r + 3, b + 3,
                                                    outline="#00ff00", width=3)
                    elif kind == "STATE":
                        magnet_on = val
                        refresh_status()
                    elif kind == "COUNT":
                        count = val
                        refresh_status()
                    elif kind == "PROGRESS":
                        try:
                            if val is None:
                                cv.delete("progress")
                            else:
                                px, py, frac = val
                                _draw_progress(cv, px, py, frac)
                        except Exception:
                            pass
                except Exception:
                    continue
            if not stopping:
                try:
                    after_id = root.after(33, tick)
                except Exception:
                    pass

        try:
            after_id = root.after(33, tick)
        except Exception:
            after_id = None
        try:
            root.mainloop()
        except Exception:
            pass
        finally:
            # Teardown строго в Tk-потоке. Порядок важен:
            # 1) отменить висячий after (иначе таймер Tcl живёт в момент destroy);
            # 2) явно разрушить дочерний Toplevel, потом корень;
            # 3) убрать HWND по сохранённым int (winfo_id после destroy мёртв);
            # 4) разорвать цикл tick->root и собрать мусор ЗДЕСЬ — иначе
            #    объект Tkapp (Tcl-интерпретатор) доживает до GC в чужом
            #    потоке/на выходе и даёт
            #    "Tcl_AsyncDelete: async handler deleted by the wrong thread".
            #    root.destroy() сам по себе интерпретатор НЕ удаляет —
            #    его удаляет деаллокация Python-обёртки в этом же потоке.
            try:
                if after_id is not None:
                    try:
                        root.after_cancel(after_id)
                    except Exception:
                        pass
            except Exception:
                pass
            after_id = None
            stopping = True
            try:
                st.destroy()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass
            try:
                if saved_hwnd is not None:
                    OVERLAY_HWNDS.discard(saved_hwnd)
            except Exception:
                pass
            try:
                if saved_st_hwnd is not None:
                    OVERLAY_HWNDS.discard(saved_st_hwnd)
            except Exception:
                pass
            # Разрыв ссылок tick/refresh_status -> root/cv/st/*, чтобы
            # refcount обнулился здесь, а не в GC чужого потока.
            # Явные del: Python не удаляет свои locals() динамически по имени.
            try:
                del tick  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del refresh_status  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del btn_toggle  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del lbl_count  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del lbl_state  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del st  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del cv  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del root  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                import gc
                gc.collect()
            except Exception:
                pass


class NullOverlay:
    def start(self):
        pass

    def poll_action(self):
        return None

    def set_target(self, rect):
        pass

    def set_state(self, on):
        pass

    def set_count(self, n):
        pass

    def set_progress(self, x, y, frac):
        pass

    def stop(self):
        pass
