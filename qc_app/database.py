"""Oracle connections, JSON conversion, transactions, and first-run tables."""
import json
import os
import re
from pathlib import Path

import oracledb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class JsonDocument:
    def __init__(self, obj):
        self.obj = obj


class Result:
    def __init__(self, rows, rowcount):
        self.rows = iter(rows)
        self.rowcount = rowcount

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)


def settings():
    values = {key: os.getenv("ORACLE_" + key.upper()) for key in ("user", "password", "dsn", "schema")}
    values["schema"] = values["schema"] or values["user"]
    raw_show_sql = os.getenv("SHOW_SQL", "").strip().lower()
    values["show_sql"] = raw_show_sql in {"1", "true", "yes", "on"}
    if not all(values[key] for key in ("user", "password", "dsn", "schema")):
        raise ValueError("Configure ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN and ORACLE_SCHEMA in qctask/.env")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", values["schema"]):
        raise ValueError("Invalid ORACLE_SCHEMA")
    return values


class Connection:
    def __init__(self, raw, schema, show_sql=False):
        self.raw, self.schema, self.show_sql = raw, schema, show_sql

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.raw.rollback() if exc_type else self.raw.commit()
        finally:
            self.raw.close()

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def execute(self, sql, parameters=()):
        sql = sql.replace("qc_store.", self.schema + ".")
        binds = {"p" + str(i): int(value) if isinstance(value, bool) else value
                 for i, value in enumerate(parameters, 1)}
        if self.show_sql:
            print(f"SQL: {sql}")
            if binds:
                print(f"Binds: {binds}")
        with self.raw.cursor() as cursor:
            for key, value in list(binds.items()):
                if isinstance(value, JsonDocument):
                    binds[key] = json.dumps(value.obj)
                    cursor.setinputsizes(**{key: oracledb.DB_TYPE_CLOB})
            returning = re.search(r"\bRETURNING\s+(\w+)\s*$", sql, re.I)
            output = None
            if returning:
                output = cursor.var(oracledb.DB_TYPE_VARCHAR if returning[1] == "claim_number" else oracledb.DB_TYPE_NUMBER)
                binds["out_value"] = output
                sql += " INTO :out_value"
            cursor.execute(sql, binds)
            count = cursor.rowcount
            if output is not None:
                return Result([(value,) for value in (output.getvalue() or [])], count)
            if cursor.description is None:
                return Result([], count)
            names = [col[0].lower() for col in cursor.description]
            rows = []
            for row in cursor:
                values = []
                for name, value in zip(names, row):
                    if hasattr(value, "read"):
                        value = value.read()
                    if name in ("task_canonical", "claim_data") and isinstance(value, str):
                        value = json.loads(value)
                    values.append(value)
                rows.append(tuple(values))
            return Result(rows, count)

    def lock_case(self, case_id):
        try:
            self.execute("INSERT INTO qc_store.qctask_case_locks (case_id) VALUES (:p1)", (case_id,))
        except oracledb.IntegrityError as exc:
            if exc.args[0].code != 1:
                raise
        self.execute("SELECT case_id FROM qc_store.qctask_case_locks WHERE case_id = :p1 FOR UPDATE", (case_id,))


def connect_db():
    cfg = settings()
    return Connection(oracledb.connect(user=cfg["user"], password=cfg["password"], dsn=cfg["dsn"], tcp_connect_timeout=5), cfg["schema"], cfg["show_sql"])


def initialize_db():
    with connect_db() as conn:
        for statement in (ROOT / "schema.sql").read_text().split(";"):
            statement = statement.strip()
            if not statement:
                continue
            match = re.search(r"CREATE (TABLE|INDEX) qc_store\.(\w+)", statement, re.I)
            if not match:
                raise ValueError("Unsupported schema statement")
            exists = conn.execute("SELECT count(*) FROM all_objects WHERE owner = :p1 AND object_name = :p2 AND object_type = :p3",
                                  (conn.schema.upper(), match[2].upper(), match[1].upper())).fetchone()[0]
            if not exists:
                try:
                    conn.execute(statement)
                except oracledb.DatabaseError as exc:
                    if exc.args[0].code != 955:
                        raise