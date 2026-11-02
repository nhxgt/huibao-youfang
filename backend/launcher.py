"""Loopback-only desktop startup for the portable Windows distribution."""
import errno
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def bind_local_socket(port=8000, *, allow_fallback=True):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            server_socket.bind(("127.0.0.1", port))
        except OSError as error:
            if not allow_fallback or error.errno != errno.EADDRINUSE:
                raise
            server_socket.bind(("127.0.0.1", 0))
        return server_socket
    except BaseException:
        server_socket.close()
        raise


def open_when_ready(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            with opener.open(url + "/api/health", timeout=0.5) as response:
                ready = response.status == 200
            if ready:
                webbrowser.open(url)
                return
        except OSError:
            pass
        time.sleep(0.2)


def main():
    from .app import app

    explicit_port = os.getenv("WORK_REPORT_PORT")
    port = int(explicit_port) if explicit_port else 8000
    with bind_local_socket(port, allow_fallback=not explicit_port) as server_socket:
        port = server_socket.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        # ASCII also works when stdout is redirected on non-Chinese Windows.
        print(f"Work Report Platform\nURL: {url}\nClose this window to stop.", flush=True)
        auto_open = os.getenv("WORK_REPORT_OPEN_BROWSER", "1" if getattr(sys, "frozen", False) else "0")
        if auto_open == "1":
            threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))
        server.run(sockets=[server_socket])
