"""Windows current-user DPAPI protection; never falls back to plaintext."""
import base64
import ctypes
import hashlib
import hmac
import json
import sys
from ctypes import wintypes
from functools import lru_cache

SCHEME = "windows-dpapi-v1"
ENTROPY = b"work-report-assistant/model-credentials/v1"


class CredentialError(Exception):
    """Safe to expose without leaking native errors or credential values."""


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


@lru_cache(maxsize=1)
def _native_functions():
    if sys.platform != "win32":
        raise CredentialError("当前平台无法使用 Windows 加密存储。")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_ptr = ctypes.POINTER(DataBlob)
    protect = crypt.CryptProtectData
    protect.argtypes = [blob_ptr, wintypes.LPCWSTR, blob_ptr, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_ptr]
    protect.restype = wintypes.BOOL
    unprotect = crypt.CryptUnprotectData
    unprotect.argtypes = [blob_ptr, ctypes.POINTER(wintypes.LPWSTR), blob_ptr, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_ptr]
    unprotect.restype = wintypes.BOOL
    free = kernel.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    return protect, unprotect, free


def _crypt(raw, decrypt=False):
    protect, unprotect, free = _native_functions()
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    entropy_buffer = (ctypes.c_ubyte * len(ENTROPY)).from_buffer_copy(ENTROPY)
    source = DataBlob(len(raw), buffer)
    entropy = DataBlob(len(ENTROPY), entropy_buffer)
    output = DataBlob()
    try:
        # UI_FORBIDDEN; deliberately do not use LOCAL_MACHINE scope.
        success = (unprotect if decrypt else protect)(
            ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output))
        if not success:
            raise CredentialError("无法使用当前 Windows 账户加密或解密 API Key。")
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(ctypes.addressof(buffer), 0, len(raw))
        if output.pbData:
            ctypes.memset(output.pbData, 0, output.cbData)
            free(ctypes.cast(output.pbData, ctypes.c_void_p))


def protect_key(api_key, base_url):
    payload = {"api_key": api_key, "base_url": base_url,
               "checksum": hashlib.sha256((base_url + "\0" + api_key).encode()).hexdigest()}
    try:
        encrypted = _crypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return {"scheme": SCHEME, "ciphertext": base64.b64encode(encrypted).decode("ascii")}
    except (OSError, ValueError) as error:
        raise CredentialError("无法安全保存 API Key。") from None


def unprotect_key(record, base_url):
    try:
        if not isinstance(record, dict) or record.get("scheme") != SCHEME:
            raise ValueError("unknown scheme")
        encoded = record["ciphertext"]
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 65536:
            raise ValueError("invalid ciphertext")
        payload = json.loads(_crypt(base64.b64decode(encoded, validate=True), decrypt=True))
        key = payload["api_key"]
        if (not isinstance(key, str) or not 1 <= len(key) <= 4096 or key != key.strip() or
                any(c in key for c in "\r\n") or payload["base_url"] != base_url):
            raise ValueError("invalid credential")
        checksum = hashlib.sha256((base_url + "\0" + key).encode()).hexdigest()
        if not hmac.compare_digest(checksum, payload["checksum"]):
            raise ValueError("invalid integrity")
        return key
    except (OSError, ValueError, KeyError, TypeError):
        raise CredentialError("已保存的 API Key 无法读取，请重新填写。") from None


def cleared_record():
    # A tombstone also prevents an old environment variable from reviving a cleared key.
    return {"scheme": SCHEME, "cleared": True}
