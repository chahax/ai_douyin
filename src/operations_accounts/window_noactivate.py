"""Product window placement for the exact browser process owned by this worker.

No foreground activation, global keyboard/mouse input, or process-name selection.
"""


def apply_native(user32, hwnd, mode):
    if mode not in ('watch', 'background'):
        raise ValueError('Invalid display mode')
    # ShowWindow returns prior visibility, not success. Read back native state.
    # SW_SHOWNOACTIVATE=4; SW_SHOWMINNOACTIVE=7.
    user32.ShowWindow(hwnd, 4 if mode == 'watch' else 7)
    minimized = bool(user32.IsIconic(hwnd))
    if minimized != (mode == 'background'):
        raise RuntimeError('Non-activating window state not confirmed')
    return {'window_state': 'minimized' if minimized else 'normal'}


def set_owned_window(page, mode):
    import ctypes
    from ctypes import wintypes
    import psutil
    import os
    browser = page.context.browser
    if browser is None:
        raise RuntimeError('Original browser process cannot be identified')
    cdp = browser.new_browser_cdp_session()
    try:
        processes = cdp.send('SystemInfo.getProcessInfo')['processInfo']
    finally:
        cdp.detach()
    roots = [int(r['id']) for r in processes if r.get('type')=='browser']
    owned = {p.pid for p in psutil.Process(os.getpid()).children(recursive=True)}
    if len(roots)!=1 or roots[0] not in owned:
        raise RuntimeError('Browser process does not belong to this worker')
    user32 = ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    user32.IsIconic.argtypes=[wintypes.HWND]
    handles=[]
    @callback_type
    def collect(hwnd,param):
        pid=wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==roots[0]:
            name=ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd,name,len(name))
            if name.value=='Chrome_WidgetWin_1':handles.append(hwnd)
        return True
    if not user32.EnumWindows(collect,0) or len(handles)!=1:
        raise RuntimeError('Exactly one original browser window is required')
    return apply_native(user32,handles[0],mode)
