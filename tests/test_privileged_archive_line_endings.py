"""Archive-level POSIX validation for the root-owned Phase 3 bootstrap."""

from __future__ import annotations

import os
import py_compile
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVILEGED = Path("deployment/privileged")
LINUX_CONSUMED = (
    "install_helper.sh",
    "uninstall_helper.sh",
    "eoat-atlas-deploy.sudoers",
    "eoat_atlas_deploy_helper.py",
)


def _privileged_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in (root / PRIVILEGED).glob("*")
        if path.is_file() and path.parent.name != "__pycache__"
    )


def _git_bash() -> Path | None:
    bash = shutil.which("bash")
    if bash:
        return Path(bash)
    git = shutil.which("git")
    if not git:
        return None
    git_root = Path(git).resolve().parents[1]
    for candidate in (git_root / "usr" / "bin" / "bash.exe", git_root / "bin" / "bash.exe"):
        if candidate.is_file():
            return candidate
    return None


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "phase3-bootstrap.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "--output", str(archive), "HEAD", str(PRIVILEGED)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    with tarfile.open(archive) as bundle:
        bundle.extractall(tmp_path / "extract", filter="data")
    return tmp_path / "extract" / PRIVILEGED


def _shell_path(bash: Path, path: Path) -> str:
    if bash.suffix.casefold() != ".exe":
        return str(path)
    converted = subprocess.run(
        [str(bash), "-lc", 'cygpath -u "$1"', "archive-validation", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return converted.stdout.strip()


def _assert_exact_sudoers_syntax(path: Path) -> None:
    """Validate the deliberately tiny supported sudoers grammar.

    A full `visudo` run remains part of the root installer on Debian.  This
    disposable harness validates the exact static rule without requiring sudo
    to be installed on a Windows development workstation.
    """
    rules = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert rules == [
        "Cmnd_Alias EOAT_ATLAS_DEPLOY = /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 *",
        "kgray ALL=(root) NOPASSWD: EOAT_ATLAS_DEPLOY",
    ]
    assert re.fullmatch(
        r"Cmnd_Alias EOAT_ATLAS_DEPLOY = /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper\.py --request-b64 \*",
        rules[0],
    )
    assert re.fullmatch(r"kgray ALL=\(root\) NOPASSWD: EOAT_ATLAS_DEPLOY", rules[1])


def _write_fake_command(directory: Path, name: str, body: str) -> None:
    target = directory / name
    target.write_text("#!/bin/sh\nset -eu\n" + body + "\n", encoding="utf-8", newline="\n")
    target.chmod(0o755)


def test_linux_consumed_worktree_files_never_contain_cr() -> None:
    for path in _privileged_files(ROOT):
        if path.is_file():
            assert b"\r" not in path.read_bytes(), path.name
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ("*.sh text eol=lf", "*.sudoers text eol=lf", "deployment/privileged/*.py text eol=lf"):
        assert rule in attributes


def test_git_archive_bootstrap_is_lf_syntax_valid_and_sudoers_safe(tmp_path: Path) -> None:
    privileged = _archive(tmp_path)
    for path in _privileged_files(tmp_path / "extract"):
        if path.is_file():
            assert b"\r" not in path.read_bytes(), path.name
    bash = _git_bash()
    assert bash is not None, "A POSIX shell is required for bootstrap archive validation"
    for name in ("install_helper.sh", "uninstall_helper.sh"):
        subprocess.run([str(bash), "-n", str(privileged / name)], check=True, text=True, capture_output=True)
    py_compile.compile(str(privileged / "eoat_atlas_deploy_helper.py"), doraise=True)
    _assert_exact_sudoers_syntax(privileged / "eoat-atlas-deploy.sudoers")


def test_archived_install_and_uninstall_scripts_use_only_expected_bootstrap_actions(tmp_path: Path) -> None:
    privileged = _archive(tmp_path)
    bash = _git_bash()
    assert bash is not None
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    bash_environment = tmp_path / "bash-env"
    bash_environment.write_text("id() { printf '0\\n'; }\n", encoding="utf-8", newline="\n")
    _write_fake_command(
        fake_bin,
        "grep",
        """test "$1" = "-Fqx"
case "$2" in
  "kgray ALL=(root) NOPASSWD: EOAT_ATLAS_DEPLOY"|"Cmnd_Alias EOAT_ATLAS_DEPLOY = /usr/bin/python3 /usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py --request-b64 *") exit 0 ;;
  *) exit 1 ;;
esac""",
    )
    _write_fake_command(fake_bin, "install", 'printf "install %s\\n" "$*" >> "$EOAT_TEST_LOG"')
    _write_fake_command(
        fake_bin,
        "visudo",
        'test "$1" = "-cf"; printf "visudo %s %s\\n" "$1" "$2" >> "$EOAT_TEST_LOG"',
    )
    _write_fake_command(fake_bin, "rm", 'printf "rm %s\\n" "$*" >> "$EOAT_TEST_LOG"')
    _write_fake_command(fake_bin, "rmdir", 'printf "rmdir %s\\n" "$*" >> "$EOAT_TEST_LOG"')
    environment = {
        **os.environ,
        "PATH": (
            f"{_shell_path(bash, fake_bin)}:/usr/bin:/bin"
            if bash.suffix.casefold() == ".exe"
            else str(fake_bin) + os.pathsep + os.environ["PATH"]
        ),
        # Git Bash translates a Windows ``PATH`` before executing the script,
        # so an ``id`` shim there is not reliable.  ``BASH_ENV`` is scoped to
        # this non-interactive test child and gives the archived script the
        # same root-result contract without weakening the real root check.
        "BASH_ENV": _shell_path(bash, bash_environment),
        "EOAT_TEST_LOG": _shell_path(bash, log),
    }
    subprocess.run(
        [str(bash), _shell_path(bash, privileged / "install_helper.sh"), "--source-dir", _shell_path(bash, privileged)],
        check=True,
        text=True,
        capture_output=True,
        env=environment,
    )
    subprocess.run(
        [str(bash), _shell_path(bash, privileged / "uninstall_helper.sh"), "--confirm-uninstall"],
        check=True,
        text=True,
        capture_output=True,
        env=environment,
    )
    actions = log.read_text(encoding="utf-8")
    assert "visudo -cf /etc/sudoers.d/eoat-atlas-deploy" in actions
    assert "/opt/eoat-atlas/current" not in actions
    assert "rm -f /etc/sudoers.d/eoat-atlas-deploy" in actions
