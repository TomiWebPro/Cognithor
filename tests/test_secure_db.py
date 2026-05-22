#!/usr/bin/env python3
"""Validate secure_db_service works on this machine."""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from secure_db_service import SecureDbService


passed = 0
failed = 0


def test(name, ok):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


tmpdir = tempfile.mkdtemp(prefix="cognithor_test_")
print(f"Using temp dir: {tmpdir}")
print()

# --- Test 1: Basic DB creation ---
print("1. Basic DB creation and connection")
db_path = os.path.join(tmpdir, "test.db")
svc = SecureDbService(db_path, use_encryption=False)
test("service created without error", True)

conn = svc.connect()
test("connect returns sqlite3.Connection", conn is not None)
conn.close()

test("db file exists on disk", os.path.isfile(db_path))

# --- Test 2: WAL mode ---
print("\n2. WAL mode")
db_path2 = os.path.join(tmpdir, "wal.db")
svc2 = SecureDbService(db_path2, use_encryption=False, wal_mode=True)
with svc2.connection() as c:
    row = c.execute("PRAGMA journal_mode").fetchone()
    # After WAL is set, subsequent connections report 'wal'
    test("journal_mode is WAL", row[0].lower() == "wal")

# --- Test 3: Foreign keys ---
print("\n3. Foreign keys pragma")
with svc2.connection() as c:
    row = c.execute("PRAGMA foreign_keys").fetchone()
    test("foreign_keys is ON", row[0] == 1)

# --- Test 4: Creating a table ---
print("\n4. CREATE TABLE and INSERT")
svc.execute("CREATE TABLE IF NOT EXISTS test_items (id INTEGER PRIMARY KEY, name TEXT, value REAL)")
lid = svc.insert("INSERT INTO test_items (name, value) VALUES (?, ?)", ("foo", 42.0))
test("insert returns lastrowid", isinstance(lid, int) and lid > 0)
svc.execute("INSERT INTO test_items (name, value) VALUES (?, ?)", ("bar", 99.5))
svc.execute_many(
    "INSERT INTO test_items (name, value) VALUES (?, ?)",
    [("baz", 1.0), ("qux", 2.5)],
)
test("execute_many succeeds", True)

# --- Test 5: Query ---
print("\n5. Query")
rows = svc.query("SELECT * FROM test_items ORDER BY id")
test("query returns list", isinstance(rows, list))
test("query returns Row objects", all(hasattr(r, "keys") for r in rows))
test("correct row count", len(rows) == 4)
test("row values accessible by name", rows[0]["name"] == "foo")

row = svc.query_one("SELECT * FROM test_items WHERE name=?", ("bar",))
test("query_one returns a row", row is not None)
test("query_one correct value", row["value"] == 99.5)

row2 = svc.query_one("SELECT * FROM test_items WHERE name=?", ("nonexistent",))
test("query_one returns None for no match", row2 is None)

# --- Test 6: table_info and table_exists ---
print("\n6. Table metadata")
info = svc.table_info("test_items")
test("table_info returns 3 columns", len(info) == 3)
test("table_exists returns True", svc.table_exists("test_items") is True)
test("table_exists returns False for missing", svc.table_exists("no_such_table") is False)

# --- Test 7: execute_script ---
print("\n7. execute_script")
svc.execute_script("""
    CREATE TABLE IF NOT EXISTS script_test (a INTEGER);
    INSERT INTO script_test VALUES (1), (2), (3);
""")
rows = svc.query("SELECT COUNT(*) AS cnt FROM script_test")
test("execute_script inserts rows", rows[0]["cnt"] == 3)

# --- Test 8: transaction context manager ---
print("\n8. Transaction")
txn_path = os.path.join(tmpdir, "txn.db")
txn_svc = SecureDbService(txn_path)
with txn_svc.transaction() as conn:
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (100)")
row = txn_svc.query_one("SELECT COUNT(*) AS cnt FROM t")
test("transaction commits data", row["cnt"] == 1)

# Test rollback on exception
try:
    with txn_svc.transaction() as conn:
        conn.execute("INSERT INTO t VALUES (200)")
        raise ValueError("force rollback")
except ValueError:
    pass
row = txn_svc.query_one("SELECT COUNT(*) AS cnt FROM t")
test("transaction rolls back on exception", row["cnt"] == 1)

# --- Test 9: run_transaction ---
print("\n9. run_transaction")
def adder(conn):
    conn.execute("INSERT INTO t VALUES (?)", (300,))
    return "done"
result = txn_svc.run_transaction(adder)
test("run_transaction returns fn result", result == "done")
row = txn_svc.query_one("SELECT COUNT(*) AS cnt FROM t")
test("run_transaction commits data", row["cnt"] == 2)

# --- Test 10: vacuum ---
print("\n10. Vacuum")
svc2.vacuum()
test("vacuum completes without error", True)

# --- Test 11: Backup ---
print("\n11. Backup")
backup_path = os.path.join(tmpdir, "test_backup.db")
svc.backup(backup_path)
test("backup file exists", os.path.isfile(backup_path))

backup_svc = SecureDbService(backup_path)
rows = backup_svc.query("SELECT COUNT(*) AS cnt FROM test_items")
test("backup has same data", rows[0]["cnt"] == 4)
test("backup has correct values", backup_svc.query_one("SELECT name FROM test_items WHERE id=?", (1,))["name"] == "foo")

# --- Test 12: Row factory ---
print("\n12. Row factory")
with svc.connection() as conn:
    row = conn.execute("SELECT 1 AS a, 2 AS b").fetchone()
    test("row by index", row[0] == 1 and row[1] == 2)
    test("row by name", row["a"] == 1 and row["b"] == 2)
    keys = row.keys()
    test("row.keys()", list(keys) == ["a", "b"])

# --- Test 13: Retry on locked DB (verify no error for normal use) ---
print("\n13. Normal concurrent use")
import threading
results = []
errors = []
lock = threading.Lock()
def write_stuff(worker_id):
    try:
        local_svc = SecureDbService(db_path)
        for i in range(20):
            local_svc.execute(
                "INSERT INTO test_items (name, value) VALUES (?, ?)",
                (f"worker_{worker_id}_{i}", float(i)),
            )
        with lock:
            results.append(worker_id)
    except Exception as e:
        with lock:
            errors.append(e)

threads = [threading.Thread(target=write_stuff, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()

test("no errors during concurrent writes", len(errors) == 0)
test("all workers completed", len(results) == 5)

final_count = svc.query_one("SELECT COUNT(*) AS cnt FROM test_items")
test("concurrent writes persisted", final_count["cnt"] >= 4 + 100)

# --- Test 14: resolve_key ---
print("\n14. resolve_key")
from secure_db_service.key_manager import resolve_key
key = resolve_key(use_encryption=False)
test("resolve_key(False) returns None", key is None)

# Use unique names to avoid pollution from other test runs
import os
_rk_svc = "CognithorTest_svc_" + str(os.getpid())
_rk_key = "test_rk"
key = resolve_key(use_encryption=True, env_var=None, service_name=_rk_svc, key_name=_rk_key)
test("resolve_key(True, no env) returns fallback key", key == "debug_key_please_change_me")

# --- Test 15: Encryption ---
print("\n15. Encryption")
try:
    from pysqlcipher3 import dbapi2 as cipher_test
    has_cipher = True
except ImportError:
    try:
        from sqlcipher3 import dbapi2 as cipher_test
        has_cipher = True
    except ImportError:
        has_cipher = False

import logging
from io import StringIO

if has_cipher:
    enc_path = os.path.join(tmpdir, "encrypted.db")
    enc_svc = SecureDbService(enc_path, use_encryption=True)
    test("encrypted service created", True)

    enc_svc.execute("CREATE TABLE IF NOT EXISTS secret (k INTEGER, v TEXT)")
    enc_svc.execute("INSERT INTO secret VALUES (?, ?)", (1, "encrypted_data"))
    row = enc_svc.query_one("SELECT v FROM secret WHERE k=?", (1,))
    test("encrypted DB insert+query works", row is not None and row["v"] == "encrypted_data")

    test("encrypted service still has use_encryption=True", enc_svc.use_encryption is True)

    raw = open(enc_path, "rb").read()
    test("encrypted DB is not plain SQLite (first bytes not 'SQLite format')", not raw.startswith(b"SQLite format"))

else:
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.WARNING)
    logging.getLogger("secure_db_service.service").addHandler(handler)

    enc_path = os.path.join(tmpdir, "encrypted_fallback.db")
    enc_svc = SecureDbService(enc_path, use_encryption=True)
    test("enc fallback service created", True)

    enc_svc.execute("CREATE TABLE IF NOT EXISTS secret (k INTEGER, v TEXT)")
    enc_svc.execute("INSERT INTO secret VALUES (?, ?)", (1, "hello"))
    row = enc_svc.query_one("SELECT v FROM secret WHERE k=?", (1,))
    test("enc fallback DB works for CRUD", row is not None and row["v"] == "hello")

    log_output = log_capture.getvalue()
    test("fallback warning was logged", "Encryption requested but neither" in log_output)
    test("use_encryption reset to False after fallback", enc_svc.use_encryption is False)

    logging.getLogger("secure_db_service.service").removeHandler(handler)

# --- Summary ---
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")

shutil.rmtree(tmpdir)
print(f"Cleaned up {tmpdir}")

sys.exit(0 if failed == 0 else 1)
