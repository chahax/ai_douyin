"""Read-only process-token flags for native QA; no credential/group extraction."""
import ctypes
from ctypes import wintypes as w


def metadata(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    a.OpenProcessToken.argtypes = [w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
    a.GetTokenInformation.argtypes = [w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)]
    a.IsTokenRestricted.argtypes = [w.HANDLE]
    a.IsTokenRestricted.restype = w.BOOL
    a.GetSidSubAuthorityCount.argtypes = [w.LPVOID]
    a.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    a.GetSidSubAuthority.argtypes = [w.LPVOID,w.DWORD]
    a.GetSidSubAuthority.restype = ctypes.POINTER(w.DWORD)
    handle = k.OpenProcess(0x1000, False, pid)
    token = w.HANDLE()
    if not handle:
        return {'query': 'unavailable'}
    try:
        if not a.OpenProcessToken(handle, 8, ctypes.byref(token)):
            return {'query': 'unavailable'}
        result = {'restricted': bool(a.IsTokenRestricted(token))}
        needed = w.DWORD()
        a.GetTokenInformation(token,25,None,0,ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if a.GetTokenInformation(token,25,buf,len(buf),ctypes.byref(needed)):
            sid = ctypes.cast(buf,ctypes.POINTER(w.LPVOID))[0]
            count = a.GetSidSubAuthorityCount(sid)[0]
            result['integrity_rid'] = a.GetSidSubAuthority(sid,count-1)[0]
        return result
    finally:
        if token:
            k.CloseHandle(token)
        k.CloseHandle(handle)
