"""Run local HTTPS plus a read-only HTTP redirect. Does not install certificate trust."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import signal
import ssl
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    os.umask(0o077)
    local = ROOT / ".local"
    local.mkdir(mode=0o700, exist_ok=True)
    certificate = local / "localhost-cert.pem"
    private_key = local / "localhost-key.pem"
    token_file = local / "bootstrap-token.txt"
    if certificate.exists() != private_key.exists():
        raise SystemExit("Incomplete TLS setup: supply both .local/localhost-cert.pem and .local/localhost-key.pem.")
    if not certificate.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:3072", "-sha256", "-nodes",
            "-days", "90", "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-addext", "basicConstraints=critical,CA:FALSE",
            "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
            "-addext", "extendedKeyUsage=serverAuth",
            "-keyout", str(private_key), "-out", str(certificate),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "x509", "-checkend", "0", "-noout", "-in", str(certificate)], check=True)
    if not os.getenv("SCOPE_SENTINEL_BOOTSTRAP_TOKEN"):
        if not token_file.exists():
            # Exclusive creation avoids overwriting an existing setup token.
            with token_file.open("x", encoding="utf8") as target:
                target.write(secrets.token_urlsafe(48) + "\n")
        token = token_file.read_text(encoding="utf8").strip()
        if not token:
            raise SystemExit("The administrator setup token file must not be empty.")
        os.environ["SCOPE_SENTINEL_BOOTSTRAP_TOKEN"] = token
    os.environ["SCOPE_SENTINEL_AUTH_REQUIRED"] = "true"
    os.environ["SCOPE_SENTINEL_SECURE_COOKIES"] = "true"
    os.environ["SCOPE_SENTINEL_ALLOWED_HOSTS"] = "localhost,127.0.0.1"
    os.environ["SCOPE_SENTINEL_ALLOWED_ORIGINS"] = "https://localhost:8443,https://127.0.0.1:8443"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import uvicorn

    # Validate the key/certificate before starting the HTTP redirect listener.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(certificate), str(private_key))
    print("Secure workspace: https://localhost:8443/administration", flush=True)
    print("Administrator setup token is in .local/bootstrap-token.txt (unless supplied by environment).", flush=True)
    print("Certificate trust has NOT been installed. Use a trusted local certificate before browser sign-in.", flush=True)
    redirect = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "app.http_redirect:app",
        "--host", "127.0.0.1", "--port", "8000", "--no-proxy-headers",
    ], cwd=ROOT)
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=8443,
                    ssl_certfile=str(certificate), ssl_keyfile=str(private_key), proxy_headers=False)
    finally:
        if redirect.poll() is None:
            redirect.send_signal(signal.SIGINT)
            try:
                redirect.wait(timeout=5)
            except subprocess.TimeoutExpired:
                redirect.terminate()
                redirect.wait(timeout=5)


if __name__ == "__main__":
    main()
