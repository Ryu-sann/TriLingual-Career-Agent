import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


class TokenVault:
    """Optional local token storage. Key is separate from ciphertext, never in Git/logs."""

    def __init__(self, key_path: Path, data_path: Path):
        self.key_path, self.data_path = key_path, data_path
        key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not key_path.exists():
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(Fernet.generate_key())
        if key_path.stat().st_mode & 0o077:
            raise ValueError("unsafe_key_permissions")
        self.cipher = Fernet(key_path.read_bytes())

    def save(self, tokens: dict):
        self.data_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.data_path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(self.cipher.encrypt(json.dumps(tokens).encode()))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.data_path)

    def load(self):
        return json.loads(self.cipher.decrypt(self.data_path.read_bytes()))
