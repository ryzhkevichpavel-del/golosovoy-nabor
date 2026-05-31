from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
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
from .startup import current_executable, is_run_on_startup, set_run_on_startup
from .transcribers import MissingBackendError, TranscriptionError, WhisperCppTranscriber
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
        user32.MessageBoxW(None, "Голосовой набор уже запущен возле часов.", APP_NAME, 0x40)
        sys.exit(0)


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
        self.hotkey_listener: keyboard.GlobalHotKeys | None = None
        self.ui_queue: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.status_window: tk.Toplevel | None = None
        self.settings_window: tk.Toplevel | None = None
        self.history_window: tk.Toplevel | None = None
        self.device_options: list[tuple[int, str]] = []

    def run(self) -> None:
        self._build_status_window()
        self._start_tray()
        self._start_hotkey()
        self.root.after(150, self._drain_ui_queue)
        self.root.mainloop()

    def _start_tray(self) -> None:
        image = self._make_icon("idle")
        menu = pystray.Menu(
            pystray.MenuItem("Начать / остановить запись", lambda: self._post("toggle")),
            pystray.MenuItem("История", lambda: self._post("history")),
            pystray.MenuItem("Настройки", lambda: self._post("settings")),
            pystray.MenuItem("Открыть папку истории", lambda: self._post("open_history_folder")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda: self._post("quit")),
        )
        self.tray_icon = pystray.Icon("golosovoy-nabor", image, APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _start_hotkey(self) -> None:
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys({self.settings.hotkey: lambda: self._post("toggle")})
            self.hotkey_listener.start()
        except Exception as exc:
            self._set_status(f"Горячая клавиша не включилась: {exc}")

    def _restart_hotkey(self) -> None:
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        self._start_hotkey()

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
        self._set_status("Идёт запись. Нажми горячую клавишу ещё раз, чтобы остановить.")
        self._set_tray_icon("recording")
        self._show_status_window()

    def stop_recording(self) -> None:
        if not self.recorder:
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
        self._set_tray_icon("busy")
        self._set_status("Распознаю запись...")
        threading.Thread(target=self._transcribe_in_background, args=(recording.path,), daemon=True).start()

    def _transcribe_in_background(self, wav_path: Path) -> None:
        try:
            if not backend_ready(self.settings.model_name):
                ensure_backend(self.settings.model_name, progress=lambda text: self._post("status", text))
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
        self._set_status(suffix + ".")
        self._show_status_window(auto_hide=True)

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
        ttk.Combobox(frame, textvariable=model_var, values=("base", "small", "medium"), state="readonly").grid(
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

        status_label = ttk.Label(frame, textvariable=self.status_var, foreground="#555555")
        status_label.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 6))

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=8, column=0, columnspan=2, sticky="ew", pady=6)
        button_bar.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(button_bar, text="Скачать Whisper", command=lambda: self._download_backend(model_var.get())).grid(
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
        )).grid(row=0, column=2, sticky="ew", padx=4)

        help_text = (
            "Бесплатный режим работает локально через Whisper. "
            "Будущий режим OpenAI уже заложен в настройках, но сейчас выключен."
        )
        ttk.Label(frame, text=help_text, wraplength=560, foreground="#666666").grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=(20, 0)
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
    ) -> None:
        self.settings.hotkey = hotkey.strip() or "<ctrl>+<alt>+space"
        self.settings.model_name = model_name
        self.settings.language = language
        self.settings.auto_paste = bool(auto_paste)
        self.settings.save_history = bool(save_history_flag)
        self.settings.run_on_startup = bool(startup)
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
        self._set_status("Настройки сохранены.")

    def _download_backend(self, model_name: str) -> None:
        self.is_busy = True
        self._set_status("Готовлю скачивание...")
        self._set_tray_icon("busy")

        def worker() -> None:
            try:
                ensure_backend(model_name, progress=lambda text: self._post("status", text))
                self._post("status", "Whisper готов к работе.")
            except Exception as exc:
                self._post("error", f"Не удалось скачать Whisper: {exc}")
            finally:
                self.is_busy = False
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

    def _build_status_window(self) -> None:
        window = tk.Toplevel(self.root)
        self.status_window = window
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        label = ttk.Label(window, textvariable=self.status_var, padding=(14, 10), background="#202124", foreground="white")
        label.pack(fill="both", expand=True)

    def _show_status_window(self, auto_hide: bool = False) -> None:
        if not self.settings.show_status_window or not self.status_window:
            return
        self.status_window.update_idletasks()
        width = max(360, self.status_window.winfo_reqwidth())
        height = max(52, self.status_window.winfo_reqheight())
        screen_w = self.status_window.winfo_screenwidth()
        screen_h = self.status_window.winfo_screenheight()
        x = screen_w - width - 28
        y = screen_h - height - 76
        self.status_window.geometry(f"{width}x{height}+{x}+{y}")
        self.status_window.deiconify()
        if auto_hide:
            self.root.after(2600, self.status_window.withdraw)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)
        if self.settings.show_status_window and (self.is_recording or self.is_busy):
            self._show_status_window()

    def _show_error(self, text: str) -> None:
        self.is_busy = False
        self.is_recording = False
        self._set_tray_icon("idle")
        self._set_status(text)
        self._show_status_window(auto_hide=True)
        messagebox.showerror(APP_NAME, text)

    def _set_tray_icon(self, mode: str) -> None:
        if self.tray_icon:
            self.tray_icon.icon = self._make_icon(mode)

    @staticmethod
    def _make_icon(mode: str) -> Image.Image:
        colors = {
            "idle": ("#2563eb", "#ffffff"),
            "recording": ("#dc2626", "#ffffff"),
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
