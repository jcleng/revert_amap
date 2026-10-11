#!/usr/bin/env python3
"""Query the persistent JADX TCP server."""
import sys, socket

PORT = 47811

def query(cmd, timeout=600):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=15)
    s.settimeout(timeout)
    s.sendall((cmd + "\n").encode("utf-8"))
    buf = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            s.close()
            return "TIMEOUT"
        if not chunk:
            break
        buf += chunk
        if b"<<<END " in buf:
            break
    s.close()
    return buf.decode("utf-8", "replace")

if __name__ == "__main__":
    print(query(" ".join(sys.argv[1:])))
