#!/usr/bin/env python3
"""Test key_manager module directly."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from secure_db_service.key_manager import (
    SERVICE_NAME,
    KEY_NAME,
    FALLBACK_KEY,
    _keyring_available,
    get_key,
    set_key,
    has_key,
    get_or_create_key,
    resolve_key,
)


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


# --- Constants ---
print("1. Constants")
test("SERVICE_NAME is Cognithor", SERVICE_NAME == "Cognithor")
test("KEY_NAME is db_key", KEY_NAME == "db_key")
test("FALLBACK_KEY is set", FALLBACK_KEY == "debug_key_please_change_me")

# --- _keyring_available ---
print("\n2. _keyring_available")
available = _keyring_available()
test("returns bool", isinstance(available, bool))

# --- resolve_key ---
print("\n3. resolve_key")
# Use unique names to avoid pollution from previous runs
svc_rk = "CognithorTest_resolve_" + str(os.getpid())
key_rk = "test_rk_key"

key = resolve_key(use_encryption=False)
test("resolve_key(False) returns None", key is None)

key = resolve_key(use_encryption=True, service_name=svc_rk, key_name=key_rk)
test("resolve_key(True) returns fallback key (no key stored)", key == FALLBACK_KEY)

key = resolve_key(use_encryption=True, env_var="COGNITHOR_DB_KEY", service_name=svc_rk, key_name=key_rk)
test("resolve_key with unset env var returns fallback", key == FALLBACK_KEY)

os.environ["COGNITHOR_DB_KEY"] = "env_key_value"
key = resolve_key(use_encryption=True, env_var="COGNITHOR_DB_KEY", service_name=svc_rk, key_name=key_rk)
test("resolve_key with env var returns env value", key == "env_key_value")
del os.environ["COGNITHOR_DB_KEY"]

key = resolve_key(use_encryption=True, env_var="", service_name=svc_rk, key_name=key_rk)
test("resolve_key with empty env_var name returns fallback", key == FALLBACK_KEY)

# --- get_key / set_key / has_key ---
print("\n4. get_key / set_key / has_key")

if available:
    svc_gs = "CognithorTest_" + str(os.getpid())
    key_gs = "test_gs_key"

    test("get_key with no key returns None",
         get_key(service_name=svc_gs, key_name=key_gs) is None)
    test("has_key returns False when no key",
         has_key(service_name=svc_gs, key_name=key_gs) is False)

    ok = set_key("test_key_value", service_name=svc_gs, key_name=key_gs)
    test("set_key returns True", ok is True)
    test("has_key returns True after set",
         has_key(service_name=svc_gs, key_name=key_gs) is True)
    val = get_key(service_name=svc_gs, key_name=key_gs)
    test("get_key returns set value", val == "test_key_value")

    ok = set_key("", service_name=svc_gs, key_name=key_gs)
    test("set_key with empty string returns True", ok is True)

    val = get_key(service_name=svc_gs, key_name=key_gs)
    test("get_key with empty stored key returns None", val is None)

    ok = set_key("new_test_key", service_name=svc_gs, key_name=key_gs)
    test("set_key overwrites previous key", ok is True)
    val = get_key(service_name=svc_gs, key_name=key_gs)
    test("get_key returns new value", val == "new_test_key")

    svc_rk2 = "CognithorTest_resolve2_" + str(os.getpid())
    from secure_db_service.key_manager import get_key as gk_orig
    import secure_db_service.key_manager as km

    og = km.get_key
    km.get_key = lambda *a, **kw: None
    val2 = resolve_key(use_encryption=True, service_name=svc_rk2, key_name=key_rk)
    test("resolve_key falls back when get_key returns None", val2 == FALLBACK_KEY)
    km.get_key = og

else:
    test("get_key returns None (no keyring)", get_key() is None)
    test("set_key returns False (no keyring)", set_key("x") is False)
    test("has_key returns False (no keyring)", has_key() is False)

# --- get_or_create_key ---
print("\n5. get_or_create_key")
if available:
    # Use unique service/key name to avoid collision with earlier tests
    test_svc = "CognithorTest_" + str(os.getpid())
    test_key = "test_goc_key"

    created = get_or_create_key(service_name=test_svc, key_name=test_key, length=16)
    test("get_or_create_key returns a string", isinstance(created, str))
    test("get_or_create_key returns 32-hex-char key (16 bytes)", len(created) == 32)
    test("get_or_create_key returns hex chars", all(c in "0123456789abcdef" for c in created))

    same = get_or_create_key(service_name=test_svc, key_name=test_key, length=16)
    test("get_or_create_key returns same key on second call", same == created)

    test_svc2 = "CognithorTest_uniq_" + str(os.getpid())
    new_key = get_or_create_key(service_name=test_svc2, key_name=test_key, length=8)
    test("get_or_create_key generates fresh key for new service", len(new_key) == 16)

else:
    test("get_or_create_key returns fallback behavior", get_or_create_key() == FALLBACK_KEY)

# --- Edge cases ---
print("\n6. Edge cases")
test("FALLBACK_KEY is non-empty", len(FALLBACK_KEY) > 0)

existing = get_key(service_name="NonExistentService", key_name="nonexistent_key")
test("get_key with unknown service returns None", existing is None)


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")

sys.exit(0 if failed == 0 else 1)
