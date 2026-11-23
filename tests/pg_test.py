"""Isolate each database test in its own PostgreSQL schema."""

import os
import uuid
from unittest.mock import patch
from urllib.parse import quote

import psycopg
from psycopg import sql


def isolated_schema(test):
    url = os.environ.get("PG_TEST_DATABASE_URL")
    if not url:
        test.skipTest("Set PG_TEST_DATABASE_URL to run PostgreSQL integration tests")
    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test.addCleanup(lambda: drop_schema(url, schema))
    scoped = url + ("&" if "?" in url else "?") + "options=" + quote("-csearch_path=" + schema)
    p = patch.dict(os.environ, {"DATABASE_URL": scoped})
    p.start()
    test.addCleanup(p.stop)


def drop_schema(url, schema):
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
