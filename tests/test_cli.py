"""Admin CLI tests.

This is the escape hatch for exactly the situation that motivated it: the
first-run partner account was created with an email or password the operator
never captured, and they need a way back in without redeploying or wiping
state.
"""

import importlib

import pytest

from backend import cli, users


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(users.config, "STATE_DIR", str(tmp_path))
    yield


class TestCreateAdmin:
    def test_creates_a_partner_by_default(self, capsys):
        code = cli.main(["create-admin", "--email", "partner@firm.in",
                         "--password", "adequatelength"])
        assert code == 0
        assert "Created partner account" in capsys.readouterr().out

        user = users.find_by_email("partner@firm.in")
        assert user["role"] == "partner"

    def test_can_create_other_roles(self):
        cli.main(["create-admin", "--email", "staff@firm.in",
                 "--password", "adequatelength", "--role", "staff"])
        assert users.find_by_email("staff@firm.in")["role"] == "staff"

    def test_duplicate_email_errors_cleanly(self, capsys):
        cli.main(["create-admin", "--email", "dup@firm.in",
                 "--password", "adequatelength"])
        code = cli.main(["create-admin", "--email", "dup@firm.in",
                        "--password", "adequatelength"])
        assert code == 1
        assert "already exists" in capsys.readouterr().err

    def test_short_password_rejected(self, capsys):
        code = cli.main(["create-admin", "--email", "x@firm.in",
                        "--password", "short"])
        assert code == 1
        assert "at least 8 characters" in capsys.readouterr().err
        assert users.find_by_email("x@firm.in") is None


class TestResetPassword:
    def test_resets_and_new_password_works(self):
        cli.main(["create-admin", "--email", "p@firm.in",
                 "--password", "originalpassword"])
        code = cli.main(["reset-password", "--email", "p@firm.in",
                        "--password", "brandnewpassword"])
        assert code == 0

        session = users.authenticate("p@firm.in", "brandnewpassword")
        assert session is not None
        assert users.authenticate("p@firm.in", "originalpassword") is None

    def test_unknown_email_errors_cleanly(self, capsys):
        code = cli.main(["reset-password", "--email", "nobody@firm.in",
                        "--password", "adequatelength"])
        assert code == 1
        assert "no user with email" in capsys.readouterr().err


class TestSetRole:
    def test_promotes_and_demotes(self):
        cli.main(["create-admin", "--email", "a@firm.in",
                 "--password", "adequatelength"])
        cli.main(["create-admin", "--email", "b@firm.in",
                 "--password", "adequatelength", "--role", "staff"])
        code = cli.main(["set-role", "--email", "b@firm.in", "--role", "manager"])
        assert code == 0
        assert users.find_by_email("b@firm.in")["role"] == "manager"

    def test_cannot_demote_the_last_partner(self, capsys):
        cli.main(["create-admin", "--email", "only@firm.in",
                 "--password", "adequatelength"])
        code = cli.main(["set-role", "--email", "only@firm.in", "--role", "staff"])
        assert code == 1
        assert "last active partner" in capsys.readouterr().err


class TestListUsers:
    def test_empty_store(self, capsys):
        code = cli.main(["list-users"])
        assert code == 0
        assert "No users" in capsys.readouterr().out

    def test_lists_created_users(self, capsys):
        cli.main(["create-admin", "--email", "one@firm.in",
                 "--password", "adequatelength"])
        cli.main(["create-admin", "--email", "two@firm.in",
                 "--password", "adequatelength", "--role", "staff"])
        code = cli.main(["list-users"])
        out = capsys.readouterr().out
        assert code == 0
        assert "one@firm.in" in out
        assert "two@firm.in" in out


class TestOperatesOnTheRealStore:
    """The whole point: this must touch the same store the running app reads."""

    def test_created_user_can_log_in_through_the_app(self):
        cli.main(["create-admin", "--email", "live@firm.in",
                 "--password", "adequatelength"])

        from backend.main import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.post("/api/auth/login", json={
                "email": "live@firm.in", "password": "adequatelength",
            })
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "partner"


class TestMigrateConversations:
    """
    The command rewrites stored records, so its default is to look and say
    what it would do. An operator who runs it to find out what is there must
    not find out by having it done.
    """

    OLD = ('{"id": "old", "created_at": "2026-03-01T10:00:00+00:00", '
           '"title": "t", "messages": [{"role": "assistant", "stage1": [], '
           '"stage2": [], "stage3": {"model": "m", "response": "r"}}]}')

    @pytest.fixture
    def conversations(self, tmp_path, monkeypatch):
        directory = tmp_path / "conversations"
        directory.mkdir()
        monkeypatch.setattr(users.config, "DATA_DIR", str(directory))
        (directory / "old.json").write_text(self.OLD)
        return directory

    def test_reports_without_writing_by_default(self, conversations, capsys):
        assert cli.main(["migrate-conversations"]) == 0
        out = capsys.readouterr().out
        assert "Would rewrite: old" in out
        assert "Nothing was written" in out
        assert (conversations / "old.json").read_text() == self.OLD

    def test_apply_rewrites(self, conversations, capsys):
        assert cli.main(["migrate-conversations", "--apply"]) == 0
        assert "Rewrote: old" in capsys.readouterr().out
        rewritten = (conversations / "old.json").read_text()
        assert '"stage3"' not in rewritten and '"ruling"' in rewritten

    def test_does_not_announce_the_user_store(self, conversations, capsys):
        cli.main(["migrate-conversations"])
        assert "user store" not in capsys.readouterr().out
