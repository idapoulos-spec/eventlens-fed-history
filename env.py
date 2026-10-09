"""Read KEY=VALUE files such as .env.local. Values are returned, never printed."""

from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL_ENV = HERE / ".env.local"


def read_env(path=LOCAL_ENV):
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values
