"""Read-only connection to the EventLens store as eventlens_app.

Errors are reported with a fixed message and the Postgres error code only, since a
driver message can name the host.
"""

import sys

import psycopg

from env import read_env


def connect():
    url = read_env().get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set in .env.local (run make_env.py)")
    try:
        # prepare_threshold=None: Neon's pooler (PgBouncer, transaction mode) can't keep prepared statements.
        conn = psycopg.connect(url, prepare_threshold=None, connect_timeout=15)
    except psycopg.Error as err:
        sys.exit(f"could not connect to the store ({type(err).__name__}, sqlstate {err.sqlstate})")
    # Every transaction opens READ ONLY, on top of the role's select-only grants.
    conn.read_only = True
    return conn


if __name__ == "__main__":
    with connect() as conn:
        print("connected as", conn.execute("select current_user").fetchone()[0])
