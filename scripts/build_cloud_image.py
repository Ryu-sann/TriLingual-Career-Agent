"""Use the platform's existing proxy and CA without copying credentials into image layers."""

import os
import socket
import subprocess
from urllib.parse import urlsplit

args = ["docker", "build", "--network", "host"]
seen = set()
for name in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"]:
    if os.environ.get(name):
        args += ["--build-arg", name]
        if name.lower() != "no_proxy":
            host = urlsplit(os.environ[name]).hostname
            if host and host not in seen:
                address = socket.gethostbyname(host)
                args += ["--add-host", f"{host}:{address}"]
                seen.add(host)
cert = os.environ.get("SSL_CERT_FILE")
if cert:
    args += ["--secret", f"id=cloud_ca,src={cert}"]
args += ["-t", "trilingual-career-agent:phase5", "."]
raise SystemExit(subprocess.run(args).returncode)
