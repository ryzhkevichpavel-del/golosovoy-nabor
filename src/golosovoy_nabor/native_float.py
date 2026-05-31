from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_ulong),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_ulong),
        ("biSizeImage", ctypes.c_ulong),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_ulong),
        ("biClrImportant", ctypes.c_ulong),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_ulong * 3)]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HANDLE),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
    ]


class NativeFloatButton:
    _api_configured = False

    WM_APP_UPDATE = 0x8001
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_MOUSEMOVE = 0x0200
    WM_RBUTTONUP = 0x0205
    WM_MOUSEACTIVATE = 0x0021
    WM_NCHITTEST = 0x0084

    MA_NOACTIVATE = 3
    HTCLIENT = 1

    WS_POPUP = 0x80000000
    WS_EX_LAYERED = 0x00080000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000

    SW_HIDE = 0
    SW_SHOWNA = 8
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    HWND_TOPMOST = -1

    ULW_ALPHA = 0x00000002
    AC_SRC_OVER = 0
    AC_SRC_ALPHA = 1
    BI_RGB = 0
    DIB_RGB_COLORS = 0

    def __init__(
        self,
        on_click: Callable[[], None],
        on_right_click: Callable[[], None],
        on_moved: Callable[[int, int], None],
    ) -> None:
        self.on_click = on_click
        self.on_right_click = on_right_click
        self.on_moved = on_moved
        self.state = "idle"
        self.elapsed = 0.0
        self.visible = True
        self.x = 0
        self.y = 0
        self.width = 102
        self.height = 64
        self.hwnd = 0
        self.thread_id = 0
        self._ready = threading.Event()
        self._commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._wndproc_ref = None
        self._drag_start: tuple[int, int, int, int] | None = None
        self._drag_moved = False
        self._captured = False
        self._last_tick = 0
        self._configure_win32_api()

    @classmethod
    def _configure_win32_api(cls) -> None:
        if cls._api_configured:
            return
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32

        kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        user32.RegisterClassW.restype = ctypes.c_ushort
        user32.CreateWindowExW.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.HWND,
            ctypes.wintypes.HMENU,
            ctypes.c_void_p,
            ctypes.wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = ctypes.wintypes.HWND
        user32.DefWindowProcW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(ctypes.wintypes.MSG),
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.UINT,
        ]
        user32.GetMessageW.restype = ctypes.wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
        user32.TranslateMessage.restype = ctypes.wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_longlong
        user32.PostMessageW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = ctypes.wintypes.BOOL
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
        user32.DestroyWindow.restype = ctypes.wintypes.BOOL
        user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.UINT,
        ]
        user32.SetWindowPos.restype = ctypes.wintypes.BOOL
        user32.SetCapture.argtypes = [ctypes.wintypes.HWND]
        user32.SetCapture.restype = ctypes.wintypes.HWND
        user32.ReleaseCapture.argtypes = []
        user32.ReleaseCapture.restype = ctypes.wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.GetCursorPos.restype = ctypes.wintypes.BOOL
        user32.GetDC.argtypes = [ctypes.wintypes.HWND]
        user32.GetDC.restype = ctypes.wintypes.HDC
        user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.UpdateLayeredWindow.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HDC,
            ctypes.POINTER(POINT),
            ctypes.POINTER(SIZE),
            ctypes.wintypes.HDC,
            ctypes.POINTER(POINT),
            ctypes.wintypes.COLORREF,
            ctypes.POINTER(BLENDFUNCTION),
            ctypes.wintypes.DWORD,
        ]
        user32.UpdateLayeredWindow.restype = ctypes.wintypes.BOOL

        gdi32.CreateCompatibleDC.argtypes = [ctypes.wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = ctypes.wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            ctypes.wintypes.HDC,
            ctypes.POINTER(BITMAPINFO),
            ctypes.wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = ctypes.wintypes.HANDLE
        gdi32.SelectObject.argtypes = [ctypes.wintypes.HDC, ctypes.wintypes.HANDLE]
        gdi32.SelectObject.restype = ctypes.wintypes.HANDLE
        gdi32.DeleteObject.argtypes = [ctypes.wintypes.HANDLE]
        gdi32.DeleteObject.restype = ctypes.wintypes.BOOL
        gdi32.DeleteDC.argtypes = [ctypes.wintypes.HDC]
        gdi32.DeleteDC.restype = ctypes.wintypes.BOOL

        cls._api_configured = True

    def start(self, x: int, y: int, visible: bool = True) -> None:
        self.x = int(x)
        self.y = int(y)
        self.visible = visible
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def stop(self) -> None:
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, self.WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=1)

    def set_visible(self, visible: bool) -> None:
        self._enqueue("visible", bool(visible))

    def set_state(self, state: str, elapsed: float | None = None) -> None:
        self._enqueue("state", (state, float(elapsed or 0.0)))

    def move_to(self, x: int, y: int) -> None:
        self._enqueue("move", (int(x), int(y)))

    def _enqueue(self, action: str, payload: object | None = None) -> None:
        self._commands.put((action, payload))
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, self.WM_APP_UPDATE, 0, 0)

    def _run(self) -> None:
        self._configure_win32_api()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "GolosovoyNaborFloatButton"
        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_longlong,
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        )
        self._wndproc_ref = wndproc_type(self._wndproc)

        wndclass = WNDCLASS()
        wndclass.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p).value
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wndclass))

        self.hwnd = user32.CreateWindowExW(
            self.WS_EX_LAYERED | self.WS_EX_TOPMOST | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE,
            class_name,
            "",
            self.WS_POPUP,
            self.x,
            self.y,
            self.width,
            self.height,
            None,
            None,
            hinstance,
            None,
        )
        self._redraw()
        user32.ShowWindow(self.hwnd, self.SW_SHOWNA if self.visible else self.SW_HIDE)
        self._ready.set()

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        user32 = ctypes.windll.user32
        if msg == self.WM_APP_UPDATE:
            self._drain_commands()
            return 0
        if msg == self.WM_MOUSEACTIVATE:
            return self.MA_NOACTIVATE
        if msg == self.WM_NCHITTEST:
            return self.HTCLIENT
        if msg == self.WM_LBUTTONDOWN:
            point = self._cursor_pos()
            self._drag_start = (point.x, point.y, self.x, self.y)
            self._drag_moved = False
            self._captured = True
            user32.SetCapture(hwnd)
            return 0
        if msg == self.WM_MOUSEMOVE and self._captured and self._drag_start:
            point = self._cursor_pos()
            start_x, start_y, win_x, win_y = self._drag_start
            dx = point.x - start_x
            dy = point.y - start_y
            if abs(dx) > 8 or abs(dy) > 8:
                self._drag_moved = True
            if self._drag_moved:
                self.x = win_x + dx
                self.y = win_y + dy
                user32.SetWindowPos(
                    hwnd,
                    self.HWND_TOPMOST,
                    self.x,
                    self.y,
                    0,
                    0,
                    self.SWP_NOSIZE | self.SWP_NOACTIVATE,
                )
            return 0
        if msg == self.WM_LBUTTONUP:
            if self._captured:
                self._captured = False
                user32.ReleaseCapture()
                if self._drag_moved:
                    self.on_moved(self.x, self.y)
                else:
                    self.on_click()
            self._drag_start = None
            self._drag_moved = False
            return 0
        if msg == self.WM_RBUTTONUP:
            self.on_right_click()
            return 0
        if msg == self.WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == self.WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _drain_commands(self) -> None:
        changed = False
        while True:
            try:
                action, payload = self._commands.get_nowait()
            except queue.Empty:
                break
            if action == "state" and isinstance(payload, tuple):
                self.state = str(payload[0])
                self.elapsed = float(payload[1])
                changed = True
            elif action == "visible":
                self.visible = bool(payload)
                ctypes.windll.user32.ShowWindow(self.hwnd, self.SW_SHOWNA if self.visible else self.SW_HIDE)
            elif action == "move" and isinstance(payload, tuple):
                self.x = int(payload[0])
                self.y = int(payload[1])
                ctypes.windll.user32.SetWindowPos(
                    self.hwnd,
                    self.HWND_TOPMOST,
                    self.x,
                    self.y,
                    0,
                    0,
                    self.SWP_NOSIZE | self.SWP_NOACTIVATE,
                )
        if changed:
            self._redraw()

    def _redraw(self) -> None:
        image = self._render()
        self.width, self.height = image.size
        hdc_screen = ctypes.windll.user32.GetDC(None)
        hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        bitmap_info = BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = self.width
        bitmap_info.bmiHeader.biHeight = -self.height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = self.BI_RGB
        hbitmap = ctypes.windll.gdi32.CreateDIBSection(
            hdc_screen,
            ctypes.byref(bitmap_info),
            self.DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        old_bitmap = ctypes.windll.gdi32.SelectObject(hdc_mem, hbitmap)
        pixel_bytes = self._to_premultiplied_bgra(image)
        ctypes.memmove(bits, pixel_bytes, len(pixel_bytes))

        source = POINT(0, 0)
        position = POINT(self.x, self.y)
        size = SIZE(self.width, self.height)
        blend = BLENDFUNCTION(self.AC_SRC_OVER, 0, 255, self.AC_SRC_ALPHA)
        ctypes.windll.user32.UpdateLayeredWindow(
            self.hwnd,
            hdc_screen,
            ctypes.byref(position),
            ctypes.byref(size),
            hdc_mem,
            ctypes.byref(source),
            0,
            ctypes.byref(blend),
            self.ULW_ALPHA,
        )
        ctypes.windll.gdi32.SelectObject(hdc_mem, old_bitmap)
        ctypes.windll.gdi32.DeleteObject(hbitmap)
        ctypes.windll.gdi32.DeleteDC(hdc_mem)
        ctypes.windll.user32.ReleaseDC(None, hdc_screen)

    def _render(self) -> Image.Image:
        state = self.state
        if state == "recording":
            width, height = 140, 64
        else:
            width, height = 102, 64
        scale = 4
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        def box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            return tuple(value * scale for value in values)  # type: ignore[return-value]

        def rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
            value = hex_color.lstrip("#")
            return (
                int(value[0:2], 16),
                int(value[2:4], 16),
                int(value[4:6], 16),
                alpha,
            )

        def shadow(shape_box: tuple[int, int, int, int], radius: int, alpha: int, blur: int, y_offset: int) -> None:
            shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            left, top, right, bottom = shape_box
            shifted = (left, top + y_offset, right, bottom + y_offset)
            shadow_draw.rounded_rectangle(box(shifted), radius=radius * scale, fill=rgba("#000000", alpha))
            blurred = shadow_layer.filter(ImageFilter.GaussianBlur(blur * scale))
            image.alpha_composite(blurred)

        def rounded_gradient(
            shape_box: tuple[int, int, int, int],
            radius: int,
            top_color: str,
            bottom_color: str,
        ) -> None:
            left, top, right, bottom = box(shape_box)
            mask = Image.new("L", image.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle((left, top, right, bottom), radius=radius * scale, fill=255)
            gradient = Image.new("RGBA", image.size, (0, 0, 0, 0))
            gradient_pixels = gradient.load()
            top_rgb = tuple(int(top_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
            bottom_rgb = tuple(int(bottom_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
            span = max(1, bottom - top)
            for y_pos in range(top, bottom + 1):
                factor = (y_pos - top) / span
                color = tuple(int(top_rgb[channel] * (1 - factor) + bottom_rgb[channel] * factor) for channel in range(3))
                for x_pos in range(left, right + 1):
                    gradient_pixels[x_pos, y_pos] = (*color, 255)
            image.paste(gradient, (0, 0), mask)

        body = (8, 8, width - 8, height - 8)
        body_radius = 24

        if state == "recording":
            shadow(body, body_radius, 36, 7, 5)
            shadow(body, body_radius, 22, 15, 8)
            rounded_gradient(body, body_radius, "#2a2a2a", "#101010")
            draw.rounded_rectangle(box(body), radius=body_radius * scale, outline=rgba("#353535"), width=1 * scale)
            draw.rounded_rectangle(box((34, 26, 46, 38)), radius=3 * scale, fill=rgba("#ffffff", 246))
            text = _format_elapsed(self.elapsed)
            font = _float_font(20 * scale, bold=False)
            text_box = draw.textbbox((0, 0), text, font=font)
            text_x = 62 * scale
            text_center_y = (body[1] + body[3]) * scale / 2
            text_y = int(text_center_y - (text_box[1] + text_box[3]) / 2)
            draw.text((text_x, text_y), text, font=font, fill=rgba("#ffffff", 244))
        else:
            shadow(body, body_radius, 24, 7, 5)
            shadow(body, body_radius, 12, 14, 8)
            rounded_gradient(body, body_radius, "#ffffff", "#f4f4f1")
            draw.rounded_rectangle(box(body), radius=body_radius * scale, outline=rgba("#d7d6d1"), width=1 * scale)
            draw.arc(box((18, 9, width - 18, 32)), start=200, end=340, fill=rgba("#ffffff", 150), width=1 * scale)
            center_x, center_y = width // 2, height // 2
            if state == "processing":
                draw.ellipse(box((center_x - 12, center_y - 12, center_x + 12, center_y + 12)), outline=rgba("#d7d7d2"), width=4 * scale)
                start = (int(time.monotonic() * 8) * 24) % 360
                draw.arc(box((center_x - 12, center_y - 12, center_x + 12, center_y + 12)), start=start, end=start + 112, fill=rgba("#202020"), width=4 * scale)
            elif state == "error":
                draw.rounded_rectangle(box(body), radius=body_radius * scale, outline=rgba("#f59e0b"), width=2 * scale)
                draw.ellipse(box((center_x - 5, center_y - 5, center_x + 5, center_y + 5)), fill=rgba("#f59e0b"))
            elif state == "success":
                draw.ellipse(box((center_x - 6, center_y - 6, center_x + 6, center_y + 6)), fill=rgba("#18c86f"))
            else:
                draw.ellipse(box((center_x - 6, center_y - 6, center_x + 6, center_y + 6)), fill=rgba("#2f80ff"))

        return image.resize((width, height), Image.Resampling.LANCZOS)

    @staticmethod
    def _to_premultiplied_bgra(image: Image.Image) -> bytes:
        data = image.convert("RGBA").tobytes()
        output = bytearray(len(data))
        for index in range(0, len(data), 4):
            channel_r = data[index]
            green = data[index + 1]
            blue = data[index + 2]
            alpha = data[index + 3]
            output[index] = (blue * alpha + 127) // 255
            output[index + 1] = (green * alpha + 127) // 255
            output[index + 2] = (channel_r * alpha + 127) // 255
            output[index + 3] = alpha
        return bytes(output)

    @staticmethod
    def _cursor_pos() -> POINT:
        point = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return point


def _float_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_name = "segoeuib.ttf" if bold else "segoeui.ttf"
    font_path = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts" / font_name
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        return ImageFont.load_default()


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"
