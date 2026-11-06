"""Exercise real preference files and prompt construction in isolated homes."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def _run_profile_scenario(tmp_path: Path, scenario: str) -> None:
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    env = dict(os.environ)
    env.update({
        "HOME": str(isolated_home),
        "USERPROFILE": str(isolated_home),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    script = "\n".join([
        "from pathlib import Path",
        "from nanocode.prompt import build_system_prompt, build_system_prompt_bundle",
        "from nanocode.user_profile import handle_user_command",
        "project = Path.cwd()",
        textwrap.dedent(scenario),
    ])
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_project_language_reaches_system_prompt(tmp_path: Path) -> None:
    _run_profile_scenario(tmp_path, """
        reply = handle_user_command("set project.preferences.language zh-CN", project)
        assert "in project profile" in reply
        assert "Language: zh-CN" in handle_user_command("project", project)
        bundle = build_system_prompt_bundle(str(project))
        assert "Language: zh-CN" in bundle.prompt
        assert not (Path.home() / ".nanocode" / "USER.md").exists()
    """)


def test_project_overrides_global_and_preserves_other_preferences(tmp_path: Path) -> None:
    _run_profile_scenario(tmp_path, """
        handle_user_command("set preferences.language en-US", project)
        handle_user_command("set preferences.verbosity concise", project)
        handle_user_command("set project.preferences.language zh-CN", project)
        handle_user_command("set project.coding_style.indent_size 4", project)
        handle_user_command("set project.coding_style.indent_style spaces", project)
        handle_user_command("set project.custom_instructions Verify exit codes.", project)
        prompt = build_system_prompt(str(project))
        assert "Language: zh-CN" in prompt
        assert "Language: en-US" not in prompt
        assert "Verbosity: concise" in prompt
        assert "indent: spaces (4)" in prompt
        assert "Custom instructions: Verify exit codes." in prompt
    """)


def test_global_preferences_apply_without_project_profile(tmp_path: Path) -> None:
    _run_profile_scenario(tmp_path, """
        handle_user_command("set preferences.language en-US", project)
        prompt = build_system_prompt(str(project))
        assert "Language: en-US" in prompt
        assert not (project / ".nanocode" / "USER.md").exists()
    """)


def test_updates_and_reset_refresh_prompt_in_same_process(tmp_path: Path) -> None:
    _run_profile_scenario(tmp_path, """
        handle_user_command("set preferences.language en-US", project)
        handle_user_command("set project.preferences.language zh-CN", project)
        assert "Language: zh-CN" in build_system_prompt(str(project))
        handle_user_command("set project.preferences.language ja-JP", project)
        updated = build_system_prompt(str(project))
        assert "Language: ja-JP" in updated
        assert "Language: zh-CN" not in updated
        handle_user_command("reset", project)
        reset = build_system_prompt(str(project))
        assert "Language: en-US" in reset
        assert "Language: ja-JP" not in reset
    """)


def test_project_preferences_do_not_leak_to_another_cwd(tmp_path: Path) -> None:
    _run_profile_scenario(tmp_path, """
        handle_user_command("set project.preferences.language zh-CN", project)
        other_project = project.parent / "other_project"
        other_project.mkdir()
        assert "Language: zh-CN" in build_system_prompt(str(project))
        assert "Language: zh-CN" not in build_system_prompt(str(other_project))
    """)


def test_absent_or_unparsed_profiles_do_not_add_empty_section(tmp_path: Path) -> None:
    _run_profile_scenario(tmp_path, """
        assert "## User Profile" not in build_system_prompt(str(project))
        profile_path = project / ".nanocode" / "USER.md"
        profile_path.parent.mkdir()
        profile_path.write_text("# Notes\\nUnrecognized preference text.\\n", encoding="utf-8")
        assert "## User Profile" not in build_system_prompt(str(project))
    """)
