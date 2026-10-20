"""Create the admin-page verifier for a new secret, without pasting it anywhere.

Usage:  python tools/make_admin_verifier.py
Prompts for the secret (hidden), then prints a JSON block to paste over
`const VERIFIER = {...}` at the top of public/admin/admin.js.
Only a salted PBKDF2-SHA256 hash is produced; the secret itself is never written.
"""
import getpass, hashlib, json, secrets

ITERATIONS = 600_000


def make_verifier(secret: str) -> dict:
    secret = secret.strip().lower()  # must match normalisation in admin.js
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, ITERATIONS, dklen=32)
    return {"salt": salt.hex(), "iterations": ITERATIONS, "hash": digest.hex()}


if __name__ == "__main__":
    print(json.dumps(make_verifier(getpass.getpass("New admin secret: ")), indent=2))
