"""Run the real management CLI with isolated homes and filesystem state."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def management_workspace(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "arbitrary source" / "draft-workflow"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Delivery\n\nCheck real outputs.\n", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
    })

    def run(*args: str):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "nanocode.main", *args],
            cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    return home, project, source, run


def test_cli_skill_project_flag_keeps_install_inside_project(management_workspace):
    home, project, source, run = management_workspace
    result = run("skills", "add", str(source), "--project")
    installed = project / ".nanocode/skills/draft-workflow/SKILL.md"
    assert installed.is_file()
    assert installed.read_bytes() == (source / "SKILL.md").read_bytes()
    assert str(installed) in result.stdout
    assert not (home / ".nanocode/skills/draft-workflow/SKILL.md").exists()
    assert str(installed) in run("skills", "list").stdout


def test_cli_skill_name_override_does_not_require_matching_source_folder(management_workspace):
    home, project, source, run = management_workspace
    run("skills", "add", str(source), "--project", "--name", "delivery-check")
    installed = project / ".nanocode/skills/delivery-check/SKILL.md"
    assert installed.is_file()
    assert installed.read_bytes() == (source / "SKILL.md").read_bytes()
    assert not (project / ".nanocode/skills/draft-workflow").exists()
    assert not (home / ".nanocode/skills/draft-workflow").exists()
    assert "delivery-check:" in run("skills", "list").stdout


def test_cli_skill_install_defaults_to_user_scope(management_workspace):
    home, project, source, run = management_workspace
    run("skills", "add", str(source))
    installed = home / ".nanocode/skills/draft-workflow/SKILL.md"
    assert installed.is_file()
    assert not (project / ".nanocode/skills/draft-workflow").exists()


def test_cli_skill_accepts_direct_skill_file_path(management_workspace):
    home, project, source, run = management_workspace
    run("skills", "add", str(source / "SKILL.md"), "--project")
    installed = project / ".nanocode/skills/draft-workflow/SKILL.md"
    assert installed.read_bytes() == (source / "SKILL.md").read_bytes()
    assert not (home / ".nanocode/skills/draft-workflow").exists()


def test_cli_project_remove_preserves_same_named_user_skill(management_workspace):
    home, project, source, run = management_workspace
    project_copy = project / ".nanocode/skills/draft-workflow/SKILL.md"
    user_copy = home / ".nanocode/skills/draft-workflow/SKILL.md"
    project_copy.parent.mkdir(parents=True)
    user_copy.parent.mkdir(parents=True)
    project_copy.write_text("Project skill\n", encoding="utf-8")
    user_copy.write_text("User skill\n", encoding="utf-8")
    run("skills", "remove", "draft-workflow", "--project")
    assert not project_copy.exists()
    assert user_copy.read_text(encoding="utf-8") == "User skill\n"
