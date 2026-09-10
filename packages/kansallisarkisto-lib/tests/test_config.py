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


# --- staging: copying the tables onto local disk before serving them ---------


def _table_dir(root: Path, content: str = "rows") -> Path:
    (root / "df.lance").mkdir(parents=True)
    (root / "df.lance" / "data.lance").write_text(content)
    return root


def test_staging_copies_the_tables_onto_local_disk(tmp_path):
    source, target = _table_dir(tmp_path / "mount"), tmp_path / "local"
    assert config.stage_lancedb(str(source), target) == str(target)
    assert (target / "df.lance" / "data.lance").read_text() == "rows"


def test_staging_reuses_a_finished_copy(tmp_path):
    """A process restarted inside the same container must not copy the tables again."""
    source, target = _table_dir(tmp_path / "mount", "new"), _table_dir(tmp_path / "local", "old")
    (target / ".staged").touch()
    assert config.stage_lancedb(str(source), target) == str(target)
    assert (target / "df.lance" / "data.lance").read_text() == "old"


def test_staging_skips_a_source_that_is_not_there(tmp_path):
    """Nothing mounted: serve the configured URI as it is, and let the boot check say so."""
    target = tmp_path / "local"
    assert config.stage_lancedb(str(tmp_path / "absent"), target) is None
    assert not target.exists()


def test_staging_skips_object_storage(tmp_path):
    """lancedb reads s3:// and gs:// itself; there is no directory to copy."""
    assert config.stage_lancedb("s3://bucket/lance", tmp_path / "local") is None


def test_a_failed_copy_is_removed_rather_than_served(monkeypatch, tmp_path):
    """A half-copied table would look present and then fail every search."""
    source, target = _table_dir(tmp_path / "mount"), tmp_path / "local"

    def partial_copy(src: Path, dst: Path) -> None:
        (dst / "df.lance").mkdir(parents=True)
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(config, "_copy_tree", partial_copy)
    assert config.stage_lancedb(str(source), target) is None
    assert list(tmp_path.glob("local*")) == []


def test_an_interrupted_copy_is_not_mistaken_for_a_staged_one(tmp_path):
    """A process killed mid-copy never reaches its cleanup, and the restart that reuse
    exists for would then serve the fragment for good. Only a copy that finished — and
    marked itself so — is reused; anything else in the target is discarded and redone."""
    source, target = _table_dir(tmp_path / "mount", "new"), tmp_path / "local"
    (target / "df.lance").mkdir(parents=True)
    assert config.stage_lancedb(str(source), target) == str(target)
    assert (target / "df.lance" / "data.lance").read_text() == "new"


def test_staging_that_cannot_even_look_falls_back(monkeypatch, tmp_path):
    """An I/O error just listing the mount — the FUSE layer's EIO — must not take the
    boot down; the server falls back to the configured URI like any other failure."""
    source, target = _table_dir(tmp_path / "mount"), tmp_path / "local"

    def unreadable(path: Path) -> bool:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(config, "_is_populated", unreadable)
    assert config.stage_lancedb(str(source), target) is None
