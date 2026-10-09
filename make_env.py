"""Build this folder's .env.local from ~/eventlens/.env.local without printing any value.

DATABASE_URL is the owner connection string with its user and password swapped for the
read-only role eventlens_app and DATABASE_APP_PASSWORD, on Neon's pooled host
(~/eventlens/db/README.md, step 5). TWELVE_DATA_API_KEY is copied as is.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from env import HERE, LOCAL_ENV, read_env

SOURCE = Path.home() / "eventlens" / ".env.local"
APP_ROLE = "eventlens_app"


def app_url(owner_url, app_password):
    parts = urlsplit(owner_url)
    host = parts.hostname or ""
    endpoint, _, rest = host.partition(".")
    if not endpoint.endswith("-pooler"):
        endpoint += "-pooler"
    netloc = f"{APP_ROLE}:{app_password}@{endpoint}.{rest}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def main():
    source = read_env(SOURCE)
    missing = [k for k in ("DATABASE_OWNER_URL", "DATABASE_APP_PASSWORD", "TWELVE_DATA_API_KEY") if not source.get(k)]
    if missing:
        sys.exit(f"missing in {SOURCE}: {', '.join(missing)}")

    ignored = subprocess.run(["git", "check-ignore", "-q", str(LOCAL_ENV)], cwd=HERE).returncode == 0
    if not ignored:
        sys.exit(".env.local is not gitignored; nothing written")

    lines = {
        "DATABASE_URL": app_url(source["DATABASE_OWNER_URL"], source["DATABASE_APP_PASSWORD"]),
        "TWELVE_DATA_API_KEY": source["TWELVE_DATA_API_KEY"],
    }
    fd = os.open(LOCAL_ENV, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.writelines(f"{k}={v}\n" for k, v in lines.items())
    os.chmod(LOCAL_ENV, 0o600)
    print("wrote .env.local:", ", ".join(lines))


if __name__ == "__main__":
    main()
