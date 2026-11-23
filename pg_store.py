"""PostgreSQL connection shared by the two local stores."""

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("请设置 DATABASE_URL 指向 PostgreSQL，再启动服务")
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as db:
        yield db
