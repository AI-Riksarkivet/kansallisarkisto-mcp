"""Where the server looks for its tables.

The order matters more than it looks: the Docker image copies the whole workspace
to /app and installs the packages editable, so the project-root walk finds a
"project root" inside the container too. Without the existence check in step 2,
an image whose KA_LANCEDB_URI was unset would look in /app/data and never at the
mounted /data.
"""

from pathlib import Path

import pytest

from ra_mcp_kansallisarkisto_lib import config


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    monkeypatch.delenv("KA_LANCEDB_URI", raising=False)


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("KA_LANCEDB_URI", "s3://bucket/lance")
    assert config.resolve_lancedb_uri() == "s3://bucket/lance"


def test_blank_override_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("KA_LANCEDB_URI", "   ")
    monkeypatch.setattr(config, "_project_root", lambda: tmp_path)
    (tmp_path / "data").mkdir()
    assert config.resolve_lancedb_uri() == str(tmp_path / "data")


def test_existing_project_data_wins_over_the_mount(monkeypatch, tmp_path):
    project, mount = tmp_path / "project", tmp_path / "mount"
    (project / "data").mkdir(parents=True)
    mount.mkdir()
    monkeypatch.setattr(config, "_project_root", lambda: project)
    monkeypatch.setattr(config, "MOUNT_DIR", mount)
    assert config.resolve_lancedb_uri() == str(project / "data")


def test_mount_wins_when_the_project_has_no_data_dir(monkeypatch, tmp_path):
    """The container case: /app is a project root, but the data is at /data."""
    project, mount = tmp_path / "app", tmp_path / "data"
    project.mkdir()
    mount.mkdir()
    monkeypatch.setattr(config, "_project_root", lambda: project)
    monkeypatch.setattr(config, "MOUNT_DIR", mount)
    assert config.resolve_lancedb_uri() == str(mount)


def test_falls_back_to_the_project_path_when_nothing_exists(monkeypatch, tmp_path):
    """A clone that has not been ingested yet should be told the path to create."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(config, "_project_root", lambda: project)
    monkeypatch.setattr(config, "MOUNT_DIR", tmp_path / "absent")
    assert config.resolve_lancedb_uri() == str(project / "data")


def test_falls_back_to_the_mount_with_no_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_project_root", lambda: None)
    monkeypatch.setattr(config, "MOUNT_DIR", tmp_path / "absent")
    assert config.resolve_lancedb_uri() == str(tmp_path / "absent")


def test_project_root_is_this_workspace():
    root = config._project_root()
    assert root is not None
    assert (root / "pyproject.toml").exists()
    assert Path(__file__).is_relative_to(root)
