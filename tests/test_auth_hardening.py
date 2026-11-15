"""Authentication hardening.

The user store holds PBKDF2 hashes AND live session tokens, and it sits one
directory above the matters. Each item here is a way that store, or an account
in it, was reachable with less work than it should have taken.
"""

import pytest
from fastapi.testclient import TestClient

from backend import config, users

TOKEN = "test-hardening-token"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    return tmp_path


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "APP_ACCESS_TOKEN", TOKEN)
    from backend.main import app
    return TestClient(app)


def _user(email="partner@firm.in", password="a-good-password", role="partner"):
    return users.create_user(email, password, name="Test", role=role)


class TestPasswordHashing:
    def test_new_hashes_use_the_current_round_count(self):
        stored = users.hash_password("a-good-password")
        assert stored.split("$")[1] == str(users._PBKDF2_ROUNDS)
        assert users._PBKDF2_ROUNDS >= 600_000

    def test_a_hash_below_the_floor_is_rejected_not_verified(self):
        """`verify_password` honoured whatever round count the record carried,
        so a record rewritten at one round verified in microseconds and the
        work factor became advisory."""
        import hashlib
        salt, password = "abcd", "a-good-password"
        weak_digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 1).hex()
        weak = f"pbkdf2$1${salt}${weak_digest}"
        assert users.verify_password(password, weak) is False

    def test_a_legacy_hash_above_the_floor_still_verifies(self):
        """Existing accounts must not be locked out by the uplift."""
        import hashlib
        salt, password = "abcd", "a-good-password"
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 240_000).hex()
        legacy = f"pbkdf2$240000${salt}${digest}"
        assert users.verify_password(password, legacy) is True

    def test_a_legacy_hash_is_rehashed_on_successful_login(self):
        import hashlib
        password = "a-good-password"
        _user(password=password)
        # Rewrite the stored hash at the old round count.
        data = users._load()
        salt = "abcd"
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 240_000).hex()
        data["users"][0]["password"] = f"pbkdf2$240000${salt}${digest}"
        users._save(data)

        assert users.authenticate("partner@firm.in", password) is not None
        upgraded = users._load()["users"][0]["password"]
        assert upgraded.split("$")[1] == str(users._PBKDF2_ROUNDS)


class TestSessionTokensAreStoredHashed:
    def test_the_raw_token_never_appears_in_the_store(self, store):
        _user()
        session = users.authenticate("partner@firm.in", "a-good-password")
        raw = session["token"]
        assert raw not in (store / "users.json").read_text(), (
            "a plaintext session token in the store is a live credential the "
            "moment the file is readable — no password, no lockout"
        )

    def test_the_token_still_resolves(self):
        _user()
        session = users.authenticate("partner@firm.in", "a-good-password")
        assert users.resolve_session(session["token"])["email"] == "partner@firm.in"

    def test_revoking_uses_the_hash(self):
        _user()
        session = users.authenticate("partner@firm.in", "a-good-password")
        users.revoke_session(session["token"])
        assert users.resolve_session(session["token"]) is None

    def test_a_stored_hash_is_not_itself_a_usable_token(self):
        _user()
        session = users.authenticate("partner@firm.in", "a-good-password")
        stored_key = next(iter(users._load()["sessions"]))
        assert users.resolve_session(stored_key) is None


class TestPasswordChangeKillsSessions:
    def test_existing_sessions_die_with_the_old_password(self):
        user = _user()
        session = users.authenticate("partner@firm.in", "a-good-password")
        assert users.resolve_session(session["token"]) is not None

        users.update_user(user["id"], password="a-different-password")
        assert users.resolve_session(session["token"]) is None, (
            "a password is changed because it may be known to someone else; "
            "a session that outlives it defeats the reason for the change"
        )

    def test_other_users_sessions_survive(self):
        _user()
        other = _user("manager@firm.in", "another-password", "manager")
        keep = users.authenticate("manager@firm.in", "another-password")
        partner = users.find_by_email("partner@firm.in")
        users.update_user(partner["id"], password="a-different-password")
        assert users.resolve_session(keep["token"]) is not None


class TestLoginLockout:
    def test_the_attempt_budget_locks_the_account(self):
        _user()
        for _ in range(users.LOGIN_MAX_ATTEMPTS):
            assert users.authenticate("partner@firm.in", "wrong") is None
        with pytest.raises(users.LockedOut):
            users.authenticate("partner@firm.in", "a-good-password")

    def test_a_successful_login_clears_the_counter(self):
        _user()
        for _ in range(users.LOGIN_MAX_ATTEMPTS - 1):
            users.authenticate("partner@firm.in", "wrong")
        assert users.authenticate("partner@firm.in", "a-good-password")
        for _ in range(users.LOGIN_MAX_ATTEMPTS - 1):
            users.authenticate("partner@firm.in", "wrong")
        # Still under budget because the counter was reset.
        assert users.authenticate("partner@firm.in", "a-good-password")

    def test_an_unknown_email_is_also_throttled(self):
        """Otherwise the endpoint is an unlimited oracle for which addresses
        exist, and an unlimited 600k-round CPU sink."""
        for _ in range(users.LOGIN_MAX_ATTEMPTS):
            users.authenticate("nobody@firm.in", "wrong")
        with pytest.raises(users.LockedOut):
            users.authenticate("nobody@firm.in", "wrong")

    def test_a_password_reset_clears_a_lockout(self):
        user = _user()
        for _ in range(users.LOGIN_MAX_ATTEMPTS):
            users.authenticate("partner@firm.in", "wrong")
        users.update_user(user["id"], password="a-different-password")
        assert users.authenticate("partner@firm.in", "a-different-password")

    def test_the_api_answers_429_with_retry_after(self, client):
        _user()
        body = {"email": "partner@firm.in", "password": "wrong"}
        for _ in range(users.LOGIN_MAX_ATTEMPTS):
            assert client.post("/api/auth/login", json=body).status_code == 401
        locked = client.post("/api/auth/login", json=body)
        assert locked.status_code == 429
        assert "Retry-After" in locked.headers

    def test_a_correct_password_is_still_refused_while_locked(self, client):
        _user()
        for _ in range(users.LOGIN_MAX_ATTEMPTS):
            client.post("/api/auth/login",
                        json={"email": "partner@firm.in", "password": "wrong"})
        good = client.post("/api/auth/login",
                           json={"email": "partner@firm.in",
                                 "password": "a-good-password"})
        assert good.status_code == 429


class TestUnauthenticatedEndpointsDoNotDiscloseLayout:
    def test_readyz_does_not_leak_the_filesystem_or_auth_posture(self, client):
        body = client.get("/readyz").json()
        assert "state_dir" not in body
        assert "data_dir" not in body
        assert "auth_enabled" not in body.get("checks", {})
        # It must still say WHICH thing is degraded, or it is useless.
        assert "api_key_configured" in body["checks"]
        assert body["status"] in ("ready", "degraded")

    def test_the_detail_is_still_available_on_the_authenticated_health(self, client):
        body = client.get(
            "/api/health", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        assert "state_dir" in body
        assert "auth_enabled" in body


class TestInternalComputationsAreGated:
    def _matter(self):
        from backend import storage
        return storage.create_matter(
            "m1", {"notice_type": "ASMT-10", "section_invoked": "73",
                   "tax_period": "FY 2019-20", "amount_disputed": 100000},
            "gst", "pro", None)

    def _login(self, client, role):
        users.create_user(f"{role}@firm.in", "a-good-password", role=role)
        r = client.post("/api/auth/login",
                        json={"email": f"{role}@firm.in",
                              "password": "a-good-password"})
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def test_staff_cannot_read_the_exposure_arithmetic(self, client):
        self._matter()
        headers = self._login(client, "staff")
        assert client.get("/api/matters/m1/computations",
                          headers=headers).status_code == 403

    def test_a_manager_can(self, client):
        self._matter()
        headers = self._login(client, "manager")
        assert client.get("/api/matters/m1/computations",
                          headers=headers).status_code == 200


class TestFailClosed:
    def test_unreadable_store_does_not_disable_auth(self, monkeypatch, tmp_path):
        from backend import auth, config, users
        monkeypatch.setattr(config, "APP_ACCESS_TOKEN", "")
        (tmp_path / "users.json").write_text("{not json")
        monkeypatch.setattr(users, "_store_path", lambda: str(tmp_path / "users.json"))
        assert auth._auth_disabled() is False

    def test_one_client_failure_does_not_lock_the_address(self, monkeypatch, tmp_path):
        from backend import users
        monkeypatch.setattr(users, "_store_path", lambda: str(tmp_path / "users.json"))
        users.create_user("a@firm.in", "correct-horse-1", "partner") if hasattr(users, "create_user") else None
        for _ in range(users.LOGIN_MAX_ATTEMPTS):
            users.authenticate("ghost@firm.in", "x", "10.0.0.1")
        # a different email from the same address is still allowed to try
        users.authenticate("other@firm.in", "x", "10.0.0.1")


class TestGuestsReachNothingStored:
    """
    POST /api/auth/guest asks for no credential, so a guest is anyone on the
    internet. The first cut of guest mode issued a token that passed
    `require_auth` on every route, and matters are not scoped per user: an
    anonymous caller could list every stored matter and read each in full —
    client name and GSTIN included. Guests are now admitted to an allowlist
    of stateless routes and refused everywhere else.
    """

    @pytest.fixture
    def guest(self, client):
        from backend import auth, storage
        auth._GUEST_SESSIONS.clear()
        storage.create_matter("m1", {"client_name": "Real Client Pvt Ltd",
                                     "gstin": "33AAAAA0000A1Z5",
                                     "notice_type": "DRC-01"}, "gst", "pro", None)
        session = client.post("/api/auth/guest").json()
        return {"Authorization": f"Bearer {session['token']}"}

    @pytest.mark.parametrize("method,path", [
        ("get", "/api/matters"),
        ("get", "/api/matters/m1"),
        ("get", "/api/matters/m1/export"),
        ("get", "/api/matters/m1/computations"),
        ("get", "/api/matters/calendar.ics"),
        ("delete", "/api/matters/m1"),
        ("get", "/api/dashboard"),
        ("get", "/api/conversations"),
        ("post", "/api/conversations"),
        ("get", "/api/health"),
        ("get", "/api/admin/users"),
        ("get", "/api/admin/settings"),
    ])
    def test_stored_data_is_refused(self, client, guest, method, path):
        response = getattr(client, method)(path, headers=guest)
        assert response.status_code == 403, f"{method} {path}"
        assert "Real Client" not in response.text
        assert "33AAAAA0000A1Z5" not in response.text

    def test_the_matter_survives_a_guest_delete_attempt(self, client, guest):
        from backend import storage
        client.delete("/api/matters/m1", headers=guest)
        assert storage.get_matter("m1") is not None

    @pytest.mark.parametrize("path", [
        "/api/features", "/api/auth/check", "/api/panel/config"])
    def test_the_stateless_routes_stay_open(self, client, guest, path):
        assert client.get(path, headers=guest).status_code == 200

    def test_every_api_route_is_closed_to_guests_unless_listed(self, client, guest):
        """
        The allowlist is the control, so it is asserted against the route
        table itself: a route added tomorrow is refused to guests without
        anyone remembering to protect it.
        """
        from backend import auth
        from backend.main import app
        unauthenticated = {"/api/auth/login", "/api/auth/guest",
                           "/api/auth/register"}
        checked = 0
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/") or path in unauthenticated:
                continue
            concrete = path.replace("{matter_id}", "m1") \
                           .replace("{conversation_id}", "c1") \
                           .replace("{user_id}", "u1")
            for method in route.methods - {"HEAD", "OPTIONS"}:
                if (method, path) in auth.GUEST_ROUTES:
                    continue
                response = client.request(method, concrete, headers=guest)
                assert response.status_code == 403, f"{method} {path}"
                checked += 1
        assert checked >= 15, "the route table was not walked"

    def test_the_allowlist_names_only_routes_that_exist(self):
        from backend import auth
        from backend.main import app
        table = {(m, r.path) for r in app.routes
                 for m in getattr(r, "methods", None) or ()}
        assert auth.GUEST_ROUTES <= table

    def test_a_guest_session_expires(self, client, guest, monkeypatch):
        from datetime import timedelta
        from backend import auth
        later = auth._now() + timedelta(hours=auth.GUEST_SESSION_TTL_HOURS, minutes=1)
        monkeypatch.setattr(auth, "_now", lambda: later)
        assert client.get("/api/features", headers=guest).status_code == 401

    def test_guest_sessions_are_capped(self, client, monkeypatch):
        from backend import auth
        auth._GUEST_SESSIONS.clear()
        monkeypatch.setattr(auth, "GUEST_SESSION_CAP", 5)
        for _ in range(20):
            client.post("/api/auth/guest")
        assert len(auth._GUEST_SESSIONS) <= 5

    def test_the_expiry_is_not_sent_to_the_browser(self, client):
        session = client.post("/api/auth/guest").json()
        assert not any(k.startswith("_") for k in session["user"])
        check = client.get("/api/auth/check", headers={
            "Authorization": f"Bearer {session['token']}"}).json()
        assert not any(k.startswith("_") for k in check["user"])

    def test_a_firm_account_is_unaffected(self, client):
        headers = {"Authorization": f"Bearer {TOKEN}"}
        from backend import storage
        storage.create_matter("m2", {"client_name": "Another Client"},
                              "gst", "pro", None)
        assert client.get("/api/matters", headers=headers).status_code == 200
        assert client.get("/api/matters/m2", headers=headers).status_code == 200


class TestSelfRegistrationIsOptIn:
    """
    A self-registered account is a `staff` member of this firm's workspace
    and can read every stored matter. It must never be available by default.
    """

    BODY = {"email": "anyone@example.com", "password": "a-good-password",
            "name": "Anyone"}

    def test_registration_is_refused_by_default(self, client):
        response = client.post("/api/auth/register", json=self.BODY)
        assert response.status_code == 403
        assert users.find_by_email("anyone@example.com") is None

    def test_registration_works_when_the_deployment_opts_in(self, client, monkeypatch):
        monkeypatch.setattr(config, "ALLOW_SELF_REGISTRATION", True)
        response = client.post("/api/auth/register", json=self.BODY)
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "staff"

    def test_the_default_is_off(self):
        import os
        assert "ALLOW_SELF_REGISTRATION" not in os.environ
        assert config.ALLOW_SELF_REGISTRATION is False
