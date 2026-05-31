from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageDraw
from pynput import keyboard

from .audio_recorder import AudioRecorder, list_input_devices
from .config import APP_NAME, AUDIO_DIR, ensure_app_dirs, load_settings, save_settings
from .history import list_history, save_transcript
from .insert import paste_text
from .native_float import NativeFloatButton
from .startup import current_executable, is_run_on_startup, set_run_on_startup
from .transcribers import FasterWhisperTranscriber, MissingBackendError, TranscriptionError, WhisperCppTranscriber
from .whisper_assets import backend_ready, ensure_backend

_MUTEX_HANDLE: int | None = None


def ensure_single_instance() -> None:
    global _MUTEX_HANDLE
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, True, "Local\\GolosovoyNaborSingleInstance")
    if kernel32.GetLastError() == 183:
        user32.MessageBoxW(None, "Глас уже запущен возле часов.", APP_NAME, 0x40)
        sys.exit(0)


class NativeF8Hotkey:
    _HOTKEY_ID = 0x4708
    _MOD_NOREPEAT = 0x4000
    _VK_F8 = 0x77
    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012

    def __init__(self, callback) -> None:  # noqa: ANN001
        self.callback = callback
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.ready = threading.Event()
        self.error: Exception | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(timeout=2)
        if self.error:
            raise self.error

    def stop(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self._WM_QUIT, 0, 0)
        if self.thread:
            self.thread.join(timeout=1)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self._HOTKEY_ID, self._MOD_NOREPEAT, self._VK_F8):
            self.error = OSError("F8 уже занята другой программой.")
            self.ready.set()
            return
        self.ready.set()
        msg = ctypes.wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == self._WM_HOTKEY:
                    self.callback()
        finally:
            user32.UnregisterHotKey(None, self._HOTKEY_ID)


class VoiceTypingApp:
    def __init__(self) -> None:
        self.settings = load_settings()
        ensure_app_dirs(self.settings)
        self.settings.run_on_startup = is_run_on_startup()
        save_settings(self.settings)

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_windows)

        self.status_var = tk.StringVar(value="Готово")
        self.recorder: AudioRecorder | None = None
        self.is_recording = False
        self.is_busy = False
        self.tray_icon: pystray.Icon | None = None
        self.hotkey_listener: object | None = None
        self.ui_queue: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.status_window: NativeFloatButton | None = None
        self.settings_window: tk.Toplevel | None = None
        self.history_window: tk.Toplevel | None = None
        self.device_options: list[tuple[int, str]] = []
        self.float_feedback: tuple[str, float] | None = None
        self.recording_started_at: float | None = None
        self.recognition_started_at: float | None = None
        self.transcriber: FasterWhisperTranscriber | WhisperCppTranscriber | None = None
        self.transcriber_lock = threading.Lock()
        self.last_toggle_at = 0.0

    def run(self) -> None:
        self._build_status_window()
        self._start_tray()
        self._start_hotkey()
        self.root.after(150, self._drain_ui_queue)
        self.root.after(250, self._tick)
        self.root.after(800, self._warm_up_transcriber)
        self.root.mainloop()

    def _start_tray(self) -> None:
        image = self._make_icon("idle")
        menu = pystray.Menu(
            pystray.MenuItem("Начать / остановить запись", lambda icon, item: self._post("toggle"), default=True),
            pystray.MenuItem("История", lambda icon, item: self._post("history")),
            pystray.MenuItem("Настройки", lambda icon, item: self._post("settings")),
            pystray.MenuItem("Открыть папку истории", lambda icon, item: self._post("open_history_folder")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda icon, item: self._post("quit")),
        )
        self.tray_icon = pystray.Icon("golosovoy-nabor", image, APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _start_hotkey(self) -> None:
        try:
            if os.name == "nt" and self.settings.hotkey.strip().lower() == "<f8>":
                self.hotkey_listener = NativeF8Hotkey(lambda: self._post("toggle"))
            else:
                self.hotkey_listener = keyboard.GlobalHotKeys({self.settings.hotkey: lambda: self._post("toggle")})
            self.hotkey_listener.start()
        except Exception as exc:
            self._set_status(f"Горячая клавиша не включилась: {exc}")

    def _restart_hotkey(self) -> None:
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        self._start_hotkey()

    def _warm_up_transcriber(self) -> None:
        if self.settings.provider != "faster_whisper":
            return

        def worker() -> None:
            try:
                with self.transcriber_lock:
                    if not isinstance(self.transcriber, FasterWhisperTranscriber):
                        self._post("status", "Готовлюсь")
                        transcriber = FasterWhisperTranscriber(self.settings)
                        transcriber.warm_up()
                        self.transcriber = transcriber
                self._post("status", "Готово")
            except Exception:
                self._post("status", "Готово")

        threading.Thread(target=worker, daemon=True).start()

    def _post(self, action: str, payload: object | None = None) -> None:
        self.ui_queue.put((action, payload))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                action, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if action == "toggle":
                self.toggle_recording()
            elif action == "float_menu":
                self.show_float_menu()
            elif action == "settings":
                self.show_settings()
            elif action == "history":
                self.show_history()
            elif action == "open_history_folder":
                self.open_history_folder()
            elif action == "quit":
                self.quit()
            elif action == "status":
                self._set_status(str(payload))
            elif action == "error":
                self._show_error(str(payload))
            elif action == "done":
                self._after_transcription(payload)
        self.root.after(150, self._drain_ui_queue)

    def toggle_recording(self) -> None:
        now = time.monotonic()
        if now - self.last_toggle_at < 0.45:
            return
        self.last_toggle_at = now
        if self.is_busy:
            self._set_status("Подожди, я ещё распознаю прошлую запись.")
            return
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        try:
            self.recorder = AudioRecorder(
                audio_dir=AUDIO_DIR,
                sample_rate=self.settings.sample_rate,
                device_index=self.settings.device_index,
            )
            self.recorder.start()
        except Exception as exc:
            self.recorder = None
            self._show_error(f"Не удалось начать запись: {exc}")
            return

        self.is_recording = True
        self.recording_started_at = time.monotonic()
        self.recognition_started_at = None
        self.float_feedback = None
        self._set_status("Идёт запись")
        self._set_tray_icon("recording")
        self._show_status_window()

    def stop_recording(self) -> None:
        if not self.recorder:
            return
        if self.recording_started_at is not None and time.monotonic() - self.recording_started_at < 0.7:
            self._set_status("Запись только началась.")
            return
        try:
            recording = self.recorder.stop()
        except Exception as exc:
            self.is_recording = False
            self.recorder = None
            self._set_tray_icon("idle")
            self._show_error(f"Не удалось сохранить звук: {exc}")
            return

        self.is_recording = False
        self.recorder = None
        self.is_busy = True
        self.recording_started_at = None
        self.recognition_started_at = time.monotonic()
        self.float_feedback = None
        self._set_tray_icon("busy")
        self._set_status("Распознаю")
        threading.Thread(target=self._transcribe_in_background, args=(recording.path,), daemon=True).start()

    def _transcribe_in_background(self, wav_path: Path) -> None:
        try:
            if self.settings.provider == "faster_whisper":
                with self.transcriber_lock:
                    if not isinstance(self.transcriber, FasterWhisperTranscriber):
                        self._post("status", "Готовлюсь")
                        self.transcriber = FasterWhisperTranscriber(self.settings)
                        self.transcriber.warm_up()
                    transcriber = self.transcriber
            else:
                if not backend_ready(self.settings.model_name):
                    ensure_backend(self.settings.model_name, progress=lambda _text: self._post("status", "Готовлюсь"))
                transcriber = WhisperCppTranscriber(self.settings)
            transcript = transcriber.transcribe(wav_path)
            self._post("done", transcript.text)
        except MissingBackendError as exc:
            self._post("error", str(exc))
        except TranscriptionError as exc:
            self._post("error", str(exc))
        except Exception as exc:
            self._post("error", f"Неожиданная ошибка: {exc}")

    def _after_transcription(self, payload: object | None) -> None:
        self.is_busy = False
        self.recording_started_at = None
        self.recognition_started_at = None
        self._set_tray_icon("idle")
        text = str(payload or "").strip()
        if not text:
            self._set_status("Пустой текст.")
            return
        pasted = paste_text(text, do_paste=self.settings.auto_paste)
        saved_path = None
        if self.settings.save_history:
            saved_path = save_transcript(text, Path(self.settings.history_dir))
        suffix = "Текст вставлен" if pasted else "Текст скопирован"
        if saved_path:
            suffix += " и сохранён в историю"
        self.float_feedback = ("success", time.monotonic() + 1.8)
        self._set_status(suffix + ".")
        self._show_status_window(auto_hide=True)

    def show_float_menu(self) -> None:
        menu = tk.Menu(
            self.root,
            tearoff=False,
            borderwidth=0,
            activeborderwidth=0,
            relief="flat",
        )
        toggle_label = "Остановить" if self.is_recording else "Начать"
        menu.add_command(label=toggle_label, command=self.toggle_recording)
        menu.add_command(label="История", command=self.show_history)
        menu.add_command(label="Настройки", command=self.show_settings)
        menu.add_separator()
        menu.add_command(label="Папка истории", command=self.open_history_folder)
        menu.add_command(label="Скрыть кнопку", command=self.hide_floating_button)
        menu.add_separator()
        menu.add_command(label="Выход", command=self.quit)
        x, y = self.root.winfo_pointerxy()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def show_settings(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("Настройки")
        window.geometry("620x520")
        window.minsize(560, 460)

        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Горячая клавиша").grid(row=0, column=0, sticky="w", pady=6)
        hotkey_var = tk.StringVar(value=self.settings.hotkey)
        ttk.Entry(frame, textvariable=hotkey_var).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(frame, text="Модель").grid(row=1, column=0, sticky="w", pady=6)
        model_var = tk.StringVar(value=self.settings.model_name)
        ttk.Combobox(
            frame,
            textvariable=model_var,
            values=("base", "tiny", "small", "medium"),
            state="readonly",
        ).grid(
            row=1, column=1, sticky="ew", pady=6
        )

        ttk.Label(frame, text="Язык").grid(row=2, column=0, sticky="w", pady=6)
        language_var = tk.StringVar(value=self.settings.language)
        ttk.Combobox(frame, textvariable=language_var, values=("auto", "ru", "en", "uk", "de", "fr"), state="readonly").grid(
            row=2, column=1, sticky="ew", pady=6
        )

        ttk.Label(frame, text="Микрофон").grid(row=3, column=0, sticky="w", pady=6)
        self.device_options = list_input_devices()
        device_labels = ["По умолчанию"] + [f"{idx}: {name}" for idx, name in self.device_options]
        current_label = "По умолчанию"
        if self.settings.device_index is not None:
            for idx, name in self.device_options:
                if idx == self.settings.device_index:
                    current_label = f"{idx}: {name}"
                    break
        device_var = tk.StringVar(value=current_label)
        ttk.Combobox(frame, textvariable=device_var, values=device_labels, state="readonly").grid(
            row=3, column=1, sticky="ew", pady=6
        )

        paste_var = tk.BooleanVar(value=self.settings.auto_paste)
        ttk.Checkbutton(frame, text="Вставлять текст в активное окно", variable=paste_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=6
        )

        history_var = tk.BooleanVar(value=self.settings.save_history)
        ttk.Checkbutton(frame, text="Сохранять историю диктовок", variable=history_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=6
        )

        startup_var = tk.BooleanVar(value=self.settings.run_on_startup)
        ttk.Checkbutton(frame, text="Запускать вместе с Windows", variable=startup_var).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=6
        )

        floating_var = tk.BooleanVar(value=self.settings.show_status_window)
        ttk.Checkbutton(frame, text="Показывать маленькую кнопку на экране", variable=floating_var).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=6
        )

        status_label = ttk.Label(frame, textvariable=self.status_var, foreground="#555555")
        status_label.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 6))

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=9, column=0, columnspan=2, sticky="ew", pady=6)
        button_bar.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(button_bar, text="Подготовить модель", command=lambda: self._download_backend(model_var.get())).grid(
            row=0, column=0, sticky="ew", padx=4
        )
        ttk.Button(button_bar, text="Открыть историю", command=self.open_history_folder).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(button_bar, text="Сохранить", command=lambda: self._save_settings_from_ui(
            hotkey_var.get(),
            model_var.get(),
            language_var.get(),
            device_var.get(),
            paste_var.get(),
            history_var.get(),
            startup_var.get(),
            floating_var.get(),
        )).grid(row=0, column=2, sticky="ew", padx=4)

        help_text = (
            "Бесплатный режим работает на компьютере. "
            "Платный режим OpenAI можно будет добавить позже."
        )
        ttk.Label(frame, text=help_text, wraplength=560, foreground="#666666").grid(
            row=10, column=0, columnspan=2, sticky="ew", pady=(20, 0)
        )

    def _save_settings_from_ui(
        self,
        hotkey: str,
        model_name: str,
        language: str,
        device_label: str,
        auto_paste: bool,
        save_history_flag: bool,
        startup: bool,
        show_floating: bool,
    ) -> None:
        self.settings.hotkey = hotkey.strip() or "<f8>"
        self.settings.model_name = model_name
        self.settings.language = language
        self.settings.auto_paste = bool(auto_paste)
        self.settings.save_history = bool(save_history_flag)
        self.settings.run_on_startup = bool(startup)
        self.settings.show_status_window = bool(show_floating)
        if device_label == "По умолчанию":
            self.settings.device_index = None
        else:
            try:
                self.settings.device_index = int(device_label.split(":", 1)[0])
            except ValueError:
                self.settings.device_index = None
        save_settings(self.settings)
        set_run_on_startup(self.settings.run_on_startup, current_executable())
        self._restart_hotkey()
        self.transcriber = None
        self._warm_up_transcriber()
        self._show_status_window()
        self._set_status("Настройки сохранены.")

    def _download_backend(self, model_name: str) -> None:
        self.is_busy = True
        self.recognition_started_at = time.monotonic()
        self._set_status("Готовлю модель")
        self._set_tray_icon("busy")

        def worker() -> None:
            try:
                if self.settings.provider == "faster_whisper":
                    with self.transcriber_lock:
                        self.settings.model_name = model_name
                        transcriber = FasterWhisperTranscriber(self.settings)
                        transcriber.warm_up()
                        self.transcriber = transcriber
                else:
                    ensure_backend(model_name, progress=lambda _text: self._post("status", "Готовлю модель"))
                self._post("status", "Готово")
            except Exception as exc:
                self._post("error", f"Не удалось подготовить модель: {exc}")
            finally:
                self.is_busy = False
                self.recognition_started_at = None
                self._set_tray_icon("idle")

        threading.Thread(target=worker, daemon=True).start()

    def show_history(self) -> None:
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.destroy()
        window = tk.Toplevel(self.root)
        self.history_window = window
        window.title("История диктовок")
        window.geometry("780x520")
        window.minsize(640, 420)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(window, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Обновить", command=self.show_history).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Открыть папку", command=self.open_history_folder).pack(side="left", padx=4)

        pane = ttk.PanedWindow(window, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        list_frame = ttk.Frame(pane)
        text_frame = ttk.Frame(pane)
        pane.add(list_frame, weight=1)
        pane.add(text_frame, weight=3)

        entries = list_history(Path(self.settings.history_dir))
        listbox = tk.Listbox(list_frame)
        listbox.pack(fill="both", expand=True)
        for entry in entries:
            listbox.insert("end", f"{entry.created_at:%d.%m.%Y %H:%M}  {entry.title}")

        text_widget = tk.Text(text_frame, wrap="word")
        text_widget.pack(fill="both", expand=True)

        button_frame = ttk.Frame(text_frame)
        button_frame.pack(fill="x", pady=6)

        def selected_path() -> Path | None:
            selection = listbox.curselection()
            if not selection:
                return None
            return entries[selection[0]].path

        def load_selected(_event: object | None = None) -> None:
            path = selected_path()
            text_widget.delete("1.0", "end")
            if path:
                text_widget.insert("1.0", path.read_text(encoding="utf-8", errors="replace"))

        def copy_selected() -> None:
            text = text_widget.get("1.0", "end").strip()
            if text:
                paste_text(text, do_paste=False)
                self._set_status("Текст из истории скопирован.")

        def delete_selected() -> None:
            path = selected_path()
            if not path:
                return
            if messagebox.askyesno("Удалить", "Удалить выбранную запись истории?"):
                path.unlink(missing_ok=True)
                self.show_history()

        ttk.Button(button_frame, text="Копировать", command=copy_selected).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Удалить", command=delete_selected).pack(side="left", padx=4)
        listbox.bind("<<ListboxSelect>>", load_selected)
        if entries:
            listbox.select_set(0)
            load_selected()

    def open_history_folder(self) -> None:
        path = Path(self.settings.history_dir)
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def hide_windows(self) -> None:
        for window in (self.settings_window, self.history_window):
            if window and window.winfo_exists():
                window.withdraw()

    def hide_floating_button(self) -> None:
        self.settings.show_status_window = False
        save_settings(self.settings)
        if self.status_window:
            self.status_window.set_visible(False)
        self._set_status("Кнопка скрыта.")

    def _build_status_window(self) -> None:
        x, y = self._default_float_position()
        self.status_window = NativeFloatButton(
            on_click=lambda: self._post("toggle"),
            on_right_click=lambda: self._post("float_menu"),
            on_moved=self._save_float_position,
        )
        self.status_window.start(x, y, visible=self.settings.show_status_window)
        self._refresh_floating()

    def _show_status_window(self, auto_hide: bool = False) -> None:
        if not self.settings.show_status_window or not self.status_window:
            if self.status_window:
                self.status_window.set_visible(False)
            return
        self.status_window.set_visible(True)
        self._refresh_floating()

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)
        self._refresh_floating()

    def _show_error(self, text: str) -> None:
        self.is_busy = False
        self.is_recording = False
        self.recording_started_at = None
        self.recognition_started_at = None
        self.float_feedback = ("error", time.monotonic() + 5.0)
        self._set_tray_icon("idle")
        self._set_status(text)
        self._show_status_window()

    def _default_float_position(self) -> tuple[int, int]:
        width = 144
        height = 68
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = self.settings.floating_x
        y = self.settings.floating_y
        if x is None or y is None:
            x = screen_w - width - 28
            y = screen_h - height - 88
        x = max(0, min(int(x), screen_w - width))
        y = max(0, min(int(y), screen_h - height))
        return x, y

    def _save_float_position(self, x: int, y: int) -> None:
        self.settings.floating_x = int(x)
        self.settings.floating_y = int(y)
        save_settings(self.settings)

    def _tick(self) -> None:
        self._refresh_floating()
        self.root.after(250, self._tick)

    def _refresh_floating(self) -> None:
        if not self.status_window:
            return
        state = "idle"
        elapsed: float | None = None
        now = time.monotonic()
        if self.is_recording and self.recording_started_at is not None:
            state = "recording"
            elapsed = now - self.recording_started_at
            self.status_window.set_state(state, elapsed)
            return
        if self.is_busy and self.recognition_started_at is not None:
            state = "processing"
            elapsed = now - self.recognition_started_at
            self.status_window.set_state(state, elapsed)
            return

        if self.float_feedback:
            feedback_state, feedback_until = self.float_feedback
            if now <= feedback_until:
                state = feedback_state
            else:
                self.float_feedback = None
        self.status_window.set_state(state, elapsed)

    def _set_tray_icon(self, mode: str) -> None:
        if self.tray_icon:
            self.tray_icon.icon = self._make_icon(mode)

    @staticmethod
    def _make_icon(mode: str) -> Image.Image:
        colors = {
            "idle": ("#2563eb", "#ffffff"),
            "recording": ("#151515", "#ffffff"),
            "busy": ("#f59e0b", "#111827"),
        }
        bg, fg = colors.get(mode, colors["idle"])
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((6, 6, 58, 58), fill=bg)
        draw.rounded_rectangle((25, 14, 39, 38), radius=7, fill=fg)
        draw.arc((17, 25, 47, 51), start=0, end=180, fill=fg, width=5)
        draw.line((32, 48, 32, 56), fill=fg, width=5)
        draw.line((23, 56, 41, 56), fill=fg, width=5)
        return image

    def quit(self) -> None:
        try:
            if self.hotkey_listener:
                self.hotkey_listener.stop()
        except Exception:
            pass
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass
        try:
            if self.status_window:
                self.status_window.stop()
        except Exception:
            pass
        self.root.quit()
        self.root.destroy()


def main() -> None:
    if os.name != "nt":
        print("Эта программа сейчас рассчитана на Windows.")
        sys.exit(1)
    ensure_single_instance()
    app = VoiceTypingApp()
    app.run()


if __name__ == "__main__":
    main()
