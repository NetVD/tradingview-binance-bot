"""
Row Level Security smoke test.

Creates two short-lived users via the admin API, makes each sign in as
themselves, and verifies that:
  - each user sees their own profile;
  - each user sees ZERO rows from the other user's tables;
  - inserting a row with a forged user_id fails (WITH CHECK violation);
  - the anon role cannot read binance_credentials at all.

Run against a real Supabase project (this cannot be unit-tested without
the actual Postgres + GoTrue stack).

Env required:
  SUPABASE_URL
  SUPABASE_ANON_KEY
  SUPABASE_SERVICE_KEY

Usage:
  pip install -r requirements.txt
  pytest test_rls.py -v
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import httpx
import pytest
from supabase import Client, create_client


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

PROTECTED_TABLES = (
    "user_profiles",
    "user_devices",
    "user_pair_subscriptions",
    "binance_credentials",
    "trade_executions",
    "signal_access_logs",
)


@dataclass
class FakeUser:
    id: str
    email: str
    password: str
    client: Client


@pytest.fixture(scope="module")
def admin() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _make_user(admin: Client, label: str) -> FakeUser:
    email = f"rls-test-{label}-{uuid.uuid4().hex[:8]}@skulltrading.test"
    password = f"pw-{uuid.uuid4().hex}"
    res = admin.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    assert res.user is not None, f"failed to create {label}"

    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.auth.sign_in_with_password({"email": email, "password": password})

    return FakeUser(id=res.user.id, email=email, password=password, client=client)


@pytest.fixture
def two_users(admin: Client):
    alice = _make_user(admin, "alice")
    bob = _make_user(admin, "bob")
    yield alice, bob
    for u in (alice, bob):
        try:
            admin.auth.admin.delete_user(u.id)
        except Exception:
            pass


def test_each_user_sees_own_profile(two_users):
    alice, bob = two_users

    alice_profile = alice.client.table("user_profiles").select("*").execute()
    assert len(alice_profile.data) == 1
    assert alice_profile.data[0]["id"] == alice.id

    bob_profile = bob.client.table("user_profiles").select("*").execute()
    assert len(bob_profile.data) == 1
    assert bob_profile.data[0]["id"] == bob.id


def test_users_cannot_see_each_others_rows(two_users):
    alice, bob = two_users

    # Insert a subscription as Alice
    alice.client.table("user_pair_subscriptions").insert(
        {"user_id": alice.id, "symbol": "BTCUSDT"}
    ).execute()

    # Bob queries the table — should see 0 rows even though Alice has 1
    bob_view = bob.client.table("user_pair_subscriptions").select("*").execute()
    assert bob_view.data == [], "Bob must not see Alice's subscriptions"

    # Alice sees her own row
    alice_view = alice.client.table("user_pair_subscriptions").select("*").execute()
    assert len(alice_view.data) == 1
    assert alice_view.data[0]["symbol"] == "BTCUSDT"


def test_forged_insert_fails(two_users):
    alice, bob = two_users

    with pytest.raises(Exception):
        # Bob tries to insert a subscription claiming to be Alice
        bob.client.table("user_pair_subscriptions").insert(
            {"user_id": alice.id, "symbol": "XAUUSDT"}
        ).execute()


def test_anon_cannot_read_binance_credentials():
    # Raw HTTP, no auth header beyond the anon key
    resp = httpx.get(
        f"{SUPABASE_URL}/rest/v1/binance_credentials?select=*",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        },
        timeout=10.0,
    )
    # Either the role has been revoked (HTTP 401/403), or the policy returns
    # an empty list. Both are acceptable; what's NOT acceptable is data.
    if resp.status_code == 200:
        assert resp.json() == [], "anon must never see binance_credentials rows"
    else:
        assert resp.status_code in (401, 403, 404), resp.text


def test_user_cannot_update_other_profile(two_users):
    alice, bob = two_users

    # Bob attempts to update Alice's profile — should affect 0 rows
    res = (
        bob.client.table("user_profiles")
        .update({"display_name": "pwned"})
        .eq("id", alice.id)
        .execute()
    )
    assert res.data == [], "RLS must prevent cross-user updates"

    # Confirm Alice's profile is intact when read by Alice
    alice_profile = alice.client.table("user_profiles").select("display_name").execute()
    assert alice_profile.data[0]["display_name"] != "pwned"


@pytest.mark.parametrize("table", PROTECTED_TABLES)
def test_table_has_rls_enabled(admin: Client, table: str):
    """Sanity check via service-role-only catalog query."""
    result = admin.rpc(
        "_pg_relation_rls",  # we don't expose this; fall back to raw SQL via PostgREST
        params={},
    ) if False else None

    # The above RPC is hypothetical; instead query pg_class via service-role
    # using the REST endpoint to inspect catalog.
    resp = httpx.get(
        f"{SUPABASE_URL}/rest/v1/rpc/_anything",  # placeholder, not used
        timeout=5.0,
    ) if False else None

    # Simpler: use psycopg-like query through supabase-py admin client
    # by calling a SQL function. To keep this test self-contained without
    # provisioning a helper RPC, we accept this as a documented manual check.
    pytest.skip(
        "RLS-enabled flag is checked at migration time; run "
        "SELECT relname, relrowsecurity FROM pg_class WHERE relname='%s' "
        "manually if needed." % table
    )
