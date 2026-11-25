"""图形界面截图脚本。

给实验报告准备运行截图：启动桌面界面、自动登录到指定页面，
再用 Windows 的 ``PrintWindow`` 接口把窗口直接渲染成 PNG。

之所以不用「截整块屏幕再裁剪」的方式：那会把桌面上其他窗口的内容
一起截进来，既不准确也不礼貌。这里直接按窗口句柄取窗口自己的位图，
只截界面本身。

用法::

    python tools/capture_shots.py --out 界面截图
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import subprocess
import sys
import time
import zlib
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WINDOW_TITLE = "多人共享记账系统 · 软件工程实验三"
DEMO_ACCOUNT = "zhoucy"
DEMO_PASSWORD = "123456"
PAGES = (
    ("overview", "01_账本概览.png"),
    ("records", "02_收支记录.png"),
    ("settlement", "03_结算单.png"),
    ("member", "04_成员管理.png"),
    ("log", "05_操作日志.png"),
)


class BitmapInfoHeader(ctypes.Structure):
    """BITMAPINFOHEADER 结构。"""

    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BitmapInfo(ctypes.Structure):
    """BITMAPINFO 结构。"""

    _fields_ = [
        ("bmiHeader", BitmapInfoHeader),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def _prepare_apis() -> None:
    """声明 Win32 API 的参数类型，避免 64 位下的指针截断。"""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BitmapInfo),
        wintypes.UINT,
    ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


def find_window(title: str) -> Optional[int]:
    """按标题查找窗口。

    :param title: 窗口标题。
    :return: 窗口句柄，找不到时返回 ``None``。
    """
    handle = ctypes.windll.user32.FindWindowW(None, title)
    return None if not handle else int(handle)


def capture_window(handle: int) -> Optional[bytes]:
    """把窗口渲染成 RGB 像素数据。

    :param handle: 窗口句柄。
    :return: 形如 ``width, height, rgb_bytes`` 的元组，失败时返回 ``None``。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(handle), ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    window_dc = user32.GetWindowDC(wintypes.HWND(handle))
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    user32.PrintWindow(wintypes.HWND(handle), memory_dc, 2)

    info = BitmapInfo()
    info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(
        memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
    )
    gdi32.SelectObject(memory_dc, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(wintypes.HWND(handle), window_dc)

    raw = buffer.raw
    rgb = bytearray(width * height * 3)
    rgb[0::3] = raw[2::4]
    rgb[1::3] = raw[1::4]
    rgb[2::3] = raw[0::4]
    return width, height, bytes(rgb)


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    """把 RGB 像素编码成 PNG 文件。

    :param path: 输出路径。
    :param width: 图像宽度。
    :param height: 图像高度。
    :param rgb: RGB 像素数据。
    """
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw += rgb[row * stride : (row + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        """构造一个 PNG 数据块。"""
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    )
    payload += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


def capture_page(
    python: str, project: Path, db_path: str, page: str, output: Path
) -> bool:
    """启动界面到指定页面并截图。

    :param python: Python 解释器路径。
    :param project: 项目根目录。
    :param db_path: 数据库文件路径。
    :param page: 目标页面。
    :param output: 输出图片路径。
    :return: 截图成功时返回 ``True``。
    """
    process = subprocess.Popen(
        [
            python,
            str(project / "tools" / "capture_gui.py"),
            "--page",
            page,
            "--seconds",
            "16",
            "--db",
            db_path,
        ],
        cwd=str(project),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        handle = None
        for _ in range(40):
            time.sleep(0.4)
            handle = find_window(WINDOW_TITLE)
            if handle:
                break
        if not handle:
            return False
        time.sleep(2.0)
        data = capture_window(handle)
        if not data:
            return False
        width, height, rgb = data
        write_png(output, width, height, rgb)
        return True
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    """命令行入口。

    :return: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="批量截取图形界面")
    parser.add_argument("--out", default="界面截图", help="输出目录")
    parser.add_argument("--db", default="capture_gui.db", help="数据库文件路径")
    parser.add_argument(
        "--project", default=str(Path(__file__).resolve().parent.parent),
        help="项目根目录",
    )
    args = parser.parse_args()

    _prepare_apis()
    project = Path(args.project).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(project / args.db)

    done: List[str] = []
    for page, filename in PAGES:
        target = out_dir / filename
        if capture_page(sys.executable, project, db_path, page, target):
            done.append(filename)
            print(f"已截图：{target}")
        else:
            print(f"截图失败：{page}")
    print(f"共 {len(done)} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
