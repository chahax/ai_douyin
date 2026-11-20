"""A headed manual window must belong to the interactive Windows desktop."""
import os

from .browser_control import BrowserControlRejected


def current_desktop_name():
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    user.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user.GetThreadDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user.GetUserObjectInformationW.restype = wintypes.BOOL
    desktop = user.GetThreadDesktop(kernel.GetCurrentThreadId())
    value = ctypes.create_unicode_buffer(512)
    needed = wintypes.DWORD()
    if not desktop or not user.GetUserObjectInformationW(desktop, 2, value,
            ctypes.sizeof(value), ctypes.byref(needed)):
        return ''
    return value.value


def require_interactive_desktop():
    name = current_desktop_name()
    if name is not None and name.casefold() != 'default':
        raise BrowserControlRejected('manual_window_noninteractive_desktop',
            '人工窗口服务不在正常桌面，未另开不可见窗口；请通过已登记的Windows自启任务启动项目。')
