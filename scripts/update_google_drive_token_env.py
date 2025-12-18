from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    from config import encrypt_value
    token_path = project_root / "token_drive.json"
    env_path = project_root / ".env"

    if not token_path.exists():
        raise SystemExit(f"No existe {token_path}")

    token_json = token_path.read_text(encoding="utf-8")
    encrypted = encrypt_value(token_json)

    if env_path.exists():
        env_text = env_path.read_text(encoding="utf-8")
    else:
        env_text = ""

    line = f'GOOGLE_DRIVE_TOKEN_JSON="{encrypted}"'

    if re.search(r"^GOOGLE_DRIVE_TOKEN_JSON=", env_text, flags=re.MULTILINE):
        env_text = re.sub(
            r"^GOOGLE_DRIVE_TOKEN_JSON=.*$",
            line,
            env_text,
            flags=re.MULTILINE,
        )
    else:
        suffix = "\n" if env_text and not env_text.endswith("\n") else ""
        env_text = f"{env_text}{suffix}{line}\n"

    env_path.write_text(env_text, encoding="utf-8")
    print("OK: .env actualizado (GOOGLE_DRIVE_TOKEN_JSON)")


if __name__ == "__main__":
    main()
