"""Deployment invariants.

Each test here corresponds to a way the service has failed, or could fail, on
a hosting platform rather than in development:

- an auto-detector could not find a top-level ``app`` and refused to deploy;
- persisted state resolved to a path outside the mounted volume, so user
  accounts and matters vanished on every redeploy;
- startup aborted because an optional network check failed.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

from backend import config

ROOT = Path(__file__).resolve().parent.parent


class TestEntrypoint:
    def test_root_module_exposes_app(self):
        """The exact thing the failing deployment looked for and did not find."""
        import main

        assert hasattr(main, "app"), "main.py must define a top-level 'app'"
        assert isinstance(main.app, FastAPI)

    def test_root_app_is_the_real_app(self):
        import main
        from backend.main import app as backend_app

        assert main.app is backend_app

    def test_backend_main_still_importable_as_a_package(self):
        module = importlib.import_module("backend.main")
        assert isinstance(module.app, FastAPI)

    def test_uvicorn_target_resolves(self):
        """`uvicorn main:app` — the container CMD and the Procfile command."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import importlib;m=importlib.import_module('main');"
             "assert m.app is not None;print('ok')"],
            cwd=ROOT, capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout


class TestStatePaths:
    """State must never resolve outside the directory a volume is mounted on."""

    @pytest.mark.parametrize("data_dir,expected", [
        ("/app/data/conversations", "/app/data"),
        ("/app/data/", "/app/data"),
        ("/app/data", "/app/data"),
        ("data/conversations", "data"),
        ("data", "data"),
        ("/data", "/data"),
        ("", "data"),
    ])
    def test_state_dir_derivation(self, data_dir, expected, monkeypatch):
        monkeypatch.setenv("DATA_DIR", data_dir)
        monkeypatch.delenv("STATE_DIR", raising=False)
        import backend.config as config
        importlib.reload(config)
        assert config.STATE_DIR == expected

    @pytest.mark.parametrize("data_dir", [
        "/app/data/conversations", "/app/data/", "/app/data",
    ])
    def test_state_never_escapes_the_mount(self, data_dir, monkeypatch):
        """The regression that would have silently destroyed user accounts."""
        monkeypatch.setenv("DATA_DIR", data_dir)
        monkeypatch.delenv("STATE_DIR", raising=False)
        import backend.config as config
        import backend.storage as storage
        import backend.users as users
        importlib.reload(config)
        importlib.reload(users)
        importlib.reload(storage)

        for path in (users._store_path(), storage._matters_dir(), config.DATA_DIR):
            assert path.startswith("/app/data"), \
                f"{path} falls outside the mounted volume /app/data"

    def test_explicit_state_dir_wins(self, monkeypatch):
        monkeypatch.setenv("DATA_DIR", "/somewhere/else/conversations")
        monkeypatch.setenv("STATE_DIR", "/app/data")
        import backend.config as config
        import backend.users as users
        importlib.reload(config)
        importlib.reload(users)
        assert users._store_path() == "/app/data/users.json"

    @pytest.fixture(autouse=True)
    def _restore_config(self):
        yield
        import backend.config as config
        import backend.storage as storage
        import backend.users as users
        importlib.reload(config)
        importlib.reload(users)
        importlib.reload(storage)


class TestStartupResilience:
    def test_boots_without_an_api_key(self, monkeypatch):
        """A missing key must degrade, not prevent the service from starting."""
        from fastapi.testclient import TestClient
        import backend.config as config

        monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
        from backend.main import app

        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200

    def test_readyz_reports_degraded_without_a_key(self, monkeypatch):
        from fastapi.testclient import TestClient
        import backend.config as config
        import backend.main as main

        monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
        with TestClient(main.app) as client:
            body = client.get("/readyz").json()
        assert body["status"] == "degraded"
        assert body["checks"]["api_key_configured"] is False

    def test_readyz_is_unauthenticated(self):
        """Probes must answer before any credential exists."""
        from fastapi.testclient import TestClient
        import backend.main as main

        with TestClient(main.app) as client:
            assert client.get("/readyz").status_code == 200
            assert client.get("/healthz").status_code == 200

    def test_startup_survives_a_failing_step(self, monkeypatch):
        from fastapi.testclient import TestClient
        import backend.main as main

        async def boom():
            raise RuntimeError("catalogue unreachable")

        monkeypatch.setattr(main, "validate_models", boom)
        with TestClient(main.app) as client:
            assert client.get("/healthz").status_code == 200


class TestDeploymentFiles:
    def test_procfile_targets_the_root_app(self):
        procfile = (ROOT / "Procfile").read_text()
        assert "main:app" in procfile
        assert "PORT" in procfile

    def test_dockerfile_copies_the_entrypoint(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        assert "COPY main.py" in dockerfile, \
            "the root entrypoint must be present in the image"
        assert "main:app" in dockerfile

    def test_dockerfile_binds_the_injected_port(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        assert "${PORT:-8001}" in dockerfile, \
            "must bind the platform's injected PORT, not a fixed one"

    def test_dockerfile_sets_both_state_paths(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        assert "DATA_DIR=/app/data" in dockerfile
        assert "STATE_DIR=/app/data" in dockerfile

    def test_render_blueprint_mounts_state_inside_the_disk(self):
        render = (ROOT / "render.yaml").read_text()
        assert "mountPath: /app/data" in render
        assert "/app/data/conversations" in render
        assert "STATE_DIR" in render

    def test_dockerignore_keeps_readme_needed_by_pyproject(self):
        ignore = (ROOT / ".dockerignore").read_text()
        assert "!README.md" in ignore, \
            "pyproject declares readme = README.md; excluding it breaks the build"


class TestTheLicence:
    """
    The licence is stated in four places — LICENSE, NOTICE, the README and
    the upstream-request note — and a relicensing that reaches only the first
    leaves the repository telling a reader two different things about what
    they may do with it.
    """

    def test_the_licence_file_is_mit(self):
        text = (ROOT / "LICENSE").read_text()
        assert text.startswith("MIT License")
        assert "Permission is hereby granted, free of charge" in text
        assert "CA Loganathan Anandan" in text
        assert "Apache" not in text

    def test_no_document_still_grants_under_apache(self):
        for name in ("NOTICE", "README.md", "docs/upstream-licence-request.md"):
            text = (ROOT / name).read_text()
            assert "licensed under the Apache" not in text, name
            assert "Apache License 2.0 in the accompanying" not in text, name
            assert "under Apache 2.0 either way" not in text, name

    def test_the_readme_and_notice_name_the_mit_licence(self):
        assert "[MIT License](LICENSE)" in (ROOT / "README.md").read_text()
        assert "The MIT License in the accompanying LICENSE file" in \
            (ROOT / "NOTICE").read_text()

    def test_the_upstream_acknowledgement_survives_the_change(self):
        """MIT does not make a NOTICE file travel. The credit stays anyway."""
        notice = (ROOT / "NOTICE").read_text()
        assert "Andrej Karpathy" in notice
        assert "permanent and unconditional" in notice

    def test_what_is_shared_with_upstream_is_not_overstated(self):
        """
        Three documents once said the remainder in common with upstream was
        only what "the libraries impose, not anyone's authorship". It was not:
        `git blame` still found upstream prose, a prompt among it, and the
        general council's function names and keys are the upstream author's
        choices whatever is done to the lines around them. A licence grant
        reaches only what the grantor owns, so the description has to be the
        true one, and the same one, wherever it appears.
        """
        import re

        record = (ROOT / "docs" / "upstream-provenance.md").read_text()
        figure = re.search(
            r"\*\*Byte-identical to upstream now\*\* \| \*\*(\d+)\*\*", record)
        assert figure, "the provenance record no longer states its total"

        for name in ("NOTICE", "README.md", "docs/upstream-licence-request.md"):
            text = (ROOT / name).read_text()
            assert "not anyone's authorship" not in text, name
            assert "dictated by the libraries" not in text, name
            assert "wholly owned" not in text, name
            assert f"{figure.group(1)} " in text, \
                f"{name} states a different count from the provenance record"
            assert "upstream-provenance.md" in text, name


class TestTheGoldenSetBoundary:
    """
    Two failure directions, and both have happened.

    Ignoring the whole golden set kept client matters out but also kept the
    synthetic cases out, so a fresh clone had no regression cover for the
    catalogue patterns at all. Ignoring none of it would put a real matter in a
    public repository the first time someone scored one.

    The line is `evals/golden/private/`. These assertions hold it from both
    sides, and they live here rather than in test_golden_set.py because that
    module skips itself when the set is empty — which is exactly the state
    these tests exist to detect.
    """

    def test_private_golden_cases_are_never_committed(self):
        ignore = (ROOT / ".gitignore").read_text()
        assert "evals/golden/private/" in ignore, (
            "evals/golden/private/ is where a golden case built from a real "
            "client matter goes. Removing it from .gitignore publishes the "
            "next one committed."
        )

    def test_the_synthetic_golden_set_is_committed(self):
        cases = sorted((ROOT / "evals" / "golden").glob("*.json"))
        assert cases, (
            "No golden cases are committed. The free scorer in "
            "tests/test_golden_set.py skips itself when the set is empty, so "
            "every catalogue pattern is unguarded and nothing says so."
        )

    def test_every_committed_case_is_marked_synthetic(self):
        # test_golden_set.py asserts this too, but it skips when the directory
        # is empty and it is the file someone would disable to make a failing
        # case go away. A confidentiality boundary gets two locks.
        for path in sorted((ROOT / "evals" / "golden").glob("*.json")):
            case = json.loads(path.read_text())
            assert case.get("synthetic") is True, (
                f"{path.name} is committed but not marked synthetic. A case "
                f"built from a client matter belongs in evals/golden/private/."
            )
            # The provenance note is the other half of the flag: `synthetic:
            # true` on its own is an assertion, the note is the reasoning
            # behind it. test_golden_set.py checks both, but it skips itself
            # when the directory is empty — so the second lock has to check
            # both too, or provenance has one lock rather than two.
            assert case.get("provenance"), (
                f"{path.name} is marked synthetic but carries no provenance "
                "note saying how it was built."
            )


class TestTierResolutionIsFailSafe:
    """
    The tier decides whether client identifiers are stripped before any
    request leaves the machine. A tier name that resolves to NOTHING — a typo,
    a stale stored value, a case variant of a retired alias — must never land
    on the non-anonymising tier, and a misconfigured deployment default must
    not turn every run into a 500.
    """

    def test_the_retired_free_tier_resolves_to_the_anonymising_tier(self):
        tier = config.get_tier("free")
        assert tier["key"] == "draft"
        assert tier["anonymise"] is True
        assert tier["watermark"]

    def test_alias_resolution_is_case_and_space_insensitive(self):
        for name in ("Free", "FREE", " free ", "  Free"):
            assert config.get_tier(name)["key"] == "draft", name

    def test_an_unknown_tier_never_falls_through_to_pro(self):
        for name in ("typo", "gold", "premium", "PRO_"):
            resolved = config.get_tier(name)
            assert resolved["key"] == config.FAILSAFE_TIER
            assert resolved["anonymise"] is True, (
                f"{name!r} resolved to a non-anonymising tier — a re-run of "
                "anonymised work would send real identifiers."
            )

    def test_the_failsafe_tier_anonymises(self):
        assert config.TIERS[config.FAILSAFE_TIER]["anonymise"] is True

    def test_empty_name_takes_the_deployment_default(self):
        assert config.get_tier("")["key"] == config._resolve_tier_key(
            config.DEFAULT_TIER)
        assert config.get_tier(None)["key"] == config._resolve_tier_key(
            config.DEFAULT_TIER)

    def test_a_misconfigured_default_degrades_instead_of_raising(self, monkeypatch):
        # A typo in DEFAULT_PANEL_TIER used to raise KeyError on EVERY call,
        # including well-formed ones — one dashboard typo, every run a 500.
        monkeypatch.setattr(config, "DEFAULT_TIER", "notatier")
        assert config.get_tier("draft")["key"] == "draft"
        assert config.get_tier("")["key"] == config.FAILSAFE_TIER
        assert config.get_tier(None)["anonymise"] is True

    def test_is_known_tier(self):
        assert config.is_known_tier("draft")
        assert config.is_known_tier("free")      # via the alias
        assert config.is_known_tier(" PRO ")
        assert not config.is_known_tier("typo")
        assert not config.is_known_tier("")
