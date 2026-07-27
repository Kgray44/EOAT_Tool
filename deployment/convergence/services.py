"""Application services shared by the console, unified CLI, and compatibility wrappers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from deployment.common import (
    CheckStatus,
    DeploymentError,
    redact_text,
    sha256_file,
    utc_now,
    utc_text,
)
from deployment.convergence.artifacts import (
    build_web_package,
    candidate_locator,
    copy_release_notes,
    validate_web_package,
    verify_source_bundle,
)
from deployment.convergence.diagnostics import diagnostic_request, fallback_envelope, validate_diagnostic_envelope
from deployment.convergence.platform_artifacts import (
    attach_platform_artifacts,
    inspect_attachment,
    write_attachment_receipt,
)
from deployment.manifest import manifest_identity, validate_external_manifest
from deployment.release_manager import (
    Git,
    _clone_for_dry_run,
    _remote_repository,
    build_deployment_archive,
    inspect_git_state,
    run_validation,
    validate_deployment_archive,
)
from deployment.server_updater import (
    GitHubRelease,
    _local_release,
    cache_release,
    github_releases,
    inspect_server_only,
    load_server_config,
    release_tag_commit,
    select_release,
)
from release_tools.release_identity import ArtifactDisposition, ProductReleaseIdentity

from .models import (
    CandidateRecord,
    CandidateState,
    CommandOutcome,
    DeploymentMode,
    DeploymentPlan,
    DeploymentState,
    DeploymentTransaction,
    Diagnostic,
    OperationResult,
    PublicationRecord,
    PublicationState,
    Status,
    next_action_for,
    require_transition,
    validate_deployment_transition,
)
from .receipts import ReceiptStore
from .release_set import ComponentKind, ComponentValidation, ReleaseSetComponent, SignedReleaseSet

_PINNED_PNPM = re.compile(r"^pnpm@(?P<version>[0-9][0-9A-Za-z.+-]*)$")
_PRODUCTION_HOSTS = {"eoat-atlas.gwplastics.com", "eoat-atlas-prod"}


class Publisher(Protocol):
    """Injectable immutable publisher used by real and disposable backends."""

    def promote(self, candidate: dict[str, Any]) -> None: ...
    def ensure_tag(self, candidate: dict[str, Any]) -> None: ...
    def push_branch(self, candidate: dict[str, Any]) -> None: ...
    def push_tag(self, candidate: dict[str, Any]) -> None: ...
    def ensure_release(self, candidate: dict[str, Any]) -> None: ...
    def upload_assets(self, candidate: dict[str, Any]) -> None: ...
    def attach_receipt(self, candidate: dict[str, Any], receipt: Path) -> None: ...
    def verify_step(self, candidate: dict[str, Any], step: PublicationState, receipt: dict[str, Any]) -> bool: ...


class ProcessRunner:
    """Bounded, redacting subprocess adapter; callers declare mutation stage."""

    TIMEOUTS = {
        "tool": 15,
        "git": 90,
        "github": 120,
        "web": 900,
        "test": 1800,
        "ssh": 30,
        "migration": 1800,
        "backup": 3600,
    }

    def run(
        self,
        operation: str,
        command: list[str],
        *,
        cwd: Path,
        timeout_class: str = "tool",
        mutation_stage: str = "read_only",
        remote_state_may_have_changed: bool = False,
    ) -> CommandOutcome:
        timeout = self.TIMEOUTS[timeout_class]
        started = utc_text()
        clock = time.monotonic()
        try:
            result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
            code, stdout, stderr = result.returncode, result.stdout or "", result.stderr or ""
        except subprocess.TimeoutExpired as exc:
            code, stdout, stderr = 124, exc.stdout or "", exc.stderr or "operation timed out"
        except OSError as exc:
            code, stdout, stderr = 127, "", str(exc)
        duration = round(time.monotonic() - clock, 3)
        combined = f"{stdout}\n{stderr}".casefold()
        if code == 0:
            category = "success"
        elif code == 124:
            category = "timeout"
        elif code == 127:
            category = "tool unavailable"
        elif "authentication" in combined or "access denied" in combined:
            category = "authentication"
        elif "already exists" in combined or "non-fast-forward" in combined or "conflict" in combined:
            category = "remote conflict"
        elif "permission denied" in combined:
            category = "permission denied"
        else:
            category = "command failed"
        action = None if code == 0 else "Review the redacted diagnostics and resolve the prerequisite."
        return CommandOutcome(
            operation=operation,
            command=tuple(self._safe_arg(arg) for arg in command),
            exit_code=code,
            started_at_utc=started,
            ended_at_utc=utc_text(),
            duration_seconds=duration,
            stdout=redact_text(stdout[-12000:]),
            stderr=redact_text(stderr[-12000:]),
            category=category,
            recommended_action=action,
            retryable=code in {124, 127} or category in {"authentication", "command failed"},
            mutation_stage=mutation_stage,
            local_state_changed=mutation_stage != "read_only" and code == 0,
            remote_state_may_have_changed=remote_state_may_have_changed,
        )

    @staticmethod
    def _safe_arg(value: str) -> str:
        return redact_text(value)


class SubprocessPublisher:
    """Git/GitHub implementation that verifies and never overwrites remote state."""

    def __init__(self, root: Path, runner: ProcessRunner | None = None) -> None:
        self.root, self.runner = root, runner or ProcessRunner()

    def _must(self, operation: str, command: list[str], *, mutation: bool = False) -> None:
        result = self.runner.run(
            operation,
            command,
            cwd=self.root,
            timeout_class="github" if command[0] == "gh" else "git",
            mutation_stage="remote_mutation" if mutation else "read_only",
            remote_state_may_have_changed=mutation,
        )
        if result.exit_code:
            raise DeploymentError(f"{operation} failed ({result.category}): {result.stderr or result.stdout}")

    def _repository(self) -> str:
        repository = _remote_repository(self.root)
        if not repository:
            raise DeploymentError("origin is not a GitHub repository")
        return repository

    def promote(self, candidate: dict[str, Any]) -> None:
        state = inspect_git_state(self.root)
        commit = str(candidate["candidate_commit"])
        if state.commit == commit:
            if Git(self.root).output("rev-parse", "HEAD^{tree}") != candidate["candidate_tree"]:
                raise DeploymentError("existing branch head has a conflicting candidate tree")
            return
        if not state.clean or state.commit != candidate["base_commit"]:
            raise DeploymentError("canonical source no longer matches the clean candidate base")
        bundle = Path(str(candidate["bundle_path"]))
        if not bundle.is_file():
            raise DeploymentError("candidate bundle is unavailable; candidate cannot be promoted")
        self._must("fetch exact candidate bundle", ["git", "fetch", str(bundle), commit])
        self._must("fast-forward exact candidate", ["git", "merge", "--ff-only", "FETCH_HEAD"], mutation=True)
        if Git(self.root).output("rev-parse", "HEAD^{tree}") != candidate["candidate_tree"]:
            raise DeploymentError("promoted candidate tree does not match validated candidate tree")

    def ensure_tag(self, candidate: dict[str, Any]) -> None:
        tag, commit = str(candidate["tag"]), str(candidate["candidate_commit"])
        git = Git(self.root)
        existing = git.run("rev-parse", "--verify", f"refs/tags/{tag}", check=False)
        if existing.returncode == 0:
            if git.output("rev-list", "-n", "1", tag) != commit:
                raise DeploymentError(f"refusing conflicting existing tag {tag}")
            return
        self._must(
            "create immutable annotated tag",
            ["git", "tag", "-a", tag, commit, "-m", f"EOAT Atlas {candidate['version']}"],
            mutation=True,
        )

    def push_branch(self, candidate: dict[str, Any]) -> None:
        branch = inspect_git_state(self.root).branch
        if branch in {"", "(detached)"}:
            raise DeploymentError("cannot push a detached branch")
        self._must("push candidate branch", ["git", "push", "origin", branch], mutation=True)

    def push_tag(self, candidate: dict[str, Any]) -> None:
        self._must("push immutable tag", ["git", "push", "origin", str(candidate["tag"])], mutation=True)

    def ensure_release(self, candidate: dict[str, Any]) -> None:
        repository, tag = self._repository(), str(candidate["tag"])
        view = self.runner.run(
            "inspect GitHub release",
            ["gh", "release", "view", tag, "--repo", repository, "--json", "tagName"],
            cwd=self.root,
            timeout_class="github",
        )
        if view.exit_code == 0:
            try:
                payload = json.loads(view.stdout)
            except json.JSONDecodeError as exc:
                raise DeploymentError("existing GitHub release response is malformed") from exc
            if payload.get("tagName") != tag:
                raise DeploymentError("existing GitHub release identity conflicts with candidate")
            return
        self._must(
            "create GitHub release",
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                repository,
                "--title",
                f"EOAT Atlas {candidate['version']}",
                "--notes",
                "Validated EOAT Atlas release candidate.",
            ],
            mutation=True,
        )

    def upload_assets(self, candidate: dict[str, Any]) -> None:
        repository, tag = self._repository(), str(candidate["tag"])
        directory = Path(str(candidate["artifact_path"])).parent
        artifact = Path(str(candidate["artifact_path"]))
        assets = (artifact, directory / "release_manifest.json", directory / f"{artifact.name}.sha256")
        if not all(path.is_file() for path in assets):
            raise DeploymentError("candidate assets are incomplete")
        self._must(
            "upload immutable release assets",
            ["gh", "release", "upload", tag, *map(str, assets), "--repo", repository],
            mutation=True,
        )

    def attach_receipt(self, candidate: dict[str, Any], receipt: Path) -> None:
        self._must(
            "attach publication receipt",
            ["gh", "release", "upload", str(candidate["tag"]), str(receipt), "--repo", self._repository()],
            mutation=True,
        )

    def verify_step(self, candidate: dict[str, Any], step: PublicationState, receipt: dict[str, Any]) -> bool:
        tag, commit = str(candidate["tag"]), str(candidate["candidate_commit"])
        if step is PublicationState.RELEASE_COMMIT_CREATED:
            return (
                inspect_git_state(self.root).commit == commit
                and Git(self.root).output("rev-parse", "HEAD^{tree}") == candidate["candidate_tree"]
            )
        if step is PublicationState.TAG_CREATED:
            result = Git(self.root).run("rev-parse", "--verify", f"refs/tags/{tag}", check=False)
            return result.returncode == 0 and Git(self.root).output("rev-list", "-n", "1", tag) == commit
        if step is PublicationState.BRANCH_PUSHED:
            branch = inspect_git_state(self.root).branch
            result = Git(self.root).run("merge-base", "--is-ancestor", commit, f"origin/{branch}", check=False)
            return result.returncode == 0
        if step is PublicationState.TAG_PUSHED:
            result = self.runner.run(
                "verify remote tag",
                ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}^{{}}"],
                cwd=self.root,
                timeout_class="git",
            )
            return result.exit_code == 0 and commit in result.stdout
        repository = self._repository()
        if step is PublicationState.GITHUB_RELEASE_CREATED:
            return (
                self.runner.run(
                    "verify GitHub release",
                    ["gh", "release", "view", tag, "--repo", repository],
                    cwd=self.root,
                    timeout_class="github",
                ).exit_code
                == 0
            )
        if step in {PublicationState.PRIMARY_ASSETS_UPLOADED, PublicationState.RECEIPT_ATTACHED}:
            result = self.runner.run(
                "verify GitHub assets",
                ["gh", "release", "view", tag, "--repo", repository, "--json", "assets"],
                cwd=self.root,
                timeout_class="github",
            )
            if result.exit_code:
                return False
            try:
                names = {item["name"] for item in json.loads(result.stdout).get("assets", [])}
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
            artifact = Path(str(candidate["artifact_path"])).name
            required = {artifact, f"{artifact}.sha256", "release_manifest.json"}
            if step is PublicationState.RECEIPT_ATTACHED:
                required.add(Path(str(receipt.get("receipt_path", ""))).name)
            return required <= names
        return False


class ReleaseDeploymentService:
    """The only business layer used by both the CLI and desktop console."""

    def __init__(self, root: Path, *, runner: ProcessRunner | None = None, store: ReceiptStore | None = None) -> None:
        self.root = root.resolve()
        self.runner = runner or ProcessRunner()
        self.store = store or ReceiptStore(self.root)

    def _tool(
        self, name: str, command: list[str], *, required: bool, scope: str, expected: str | None = None
    ) -> Diagnostic:
        result = self.runner.run(f"{name} availability", command, cwd=self.root, timeout_class="tool")
        if result.exit_code:
            return Diagnostic(
                name,
                Status.BLOCKED if required else Status.NOT_RUN,
                result.stderr or result.stdout,
                result.recommended_action,
                required,
                scope,
            )
        actual = (
            (result.stdout or result.stderr).strip().splitlines()[0]
            if (result.stdout or result.stderr)
            else "available"
        )
        if expected and actual != expected:
            return Diagnostic(
                name,
                Status.BLOCKED,
                f"expected {expected}; found {actual}",
                "Install or activate the repository-pinned version.",
                required,
                scope,
            )
        return Diagnostic(name, Status.PASS, actual, None, required, scope)

    def _pinned_pnpm(self) -> str | None:
        path = self.root / "web" / "package.json"
        if not path.is_file():
            return None
        try:
            package = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        match = _PINNED_PNPM.fullmatch(str(package.get("packageManager", "")))
        return match.group("version") if match else None

    @staticmethod
    def _pnpm_command() -> str:
        candidate = shutil.which("pnpm")
        if candidate:
            return candidate
        home = Path(str(os.environ.get("PNPM_HOME") or ""))
        executable = home / ("pnpm.cmd" if os.name == "nt" else "pnpm")
        return str(executable) if executable.is_file() else "pnpm"

    def readiness(self, scope: str = "candidate") -> OperationResult:
        state = inspect_git_state(self.root)
        diagnostics: list[Diagnostic] = [
            Diagnostic(
                "repository identity",
                Status.PASS,
                f"{state.root} @ {state.commit[:12]}",
                required=True,
                scope="candidate",
            ),
            Diagnostic(
                "working tree",
                Status.PASS if state.clean else Status.BLOCKED,
                "clean" if state.clean else "uncommitted changes are present: " + ", ".join((*state.modified, *state.staged, *state.untracked)[:12]),
                "Use a clean worktree.",
                True,
                "candidate",
            ),
            Diagnostic(
                "merge conflicts",
                Status.PASS if not state.conflicts else Status.BLOCKED,
                "none" if not state.conflicts else ", ".join(state.conflicts),
                "Resolve conflicts.",
                True,
                "candidate",
            ),
            Diagnostic(
                "upstream freshness",
                Status.PASS if not state.behind else Status.BLOCKED,
                f"ahead={state.ahead}, behind={state.behind}",
                "Fetch and reconcile before candidate preparation.",
                True,
                "candidate",
            ),
            Diagnostic(
                "version sources",
                Status.PASS if state.version else Status.BLOCKED,
                state.version or "version source validation failed",
                "Repair version metadata.",
                True,
                "candidate",
            ),
            self._tool("Git", ["git", "--version"], required=True, scope="candidate"),
            self._tool("Python", ["python", "--version"], required=True, scope="candidate"),
            Diagnostic(
                "candidate storage",
                Status.PASS if self._storage_writable() else Status.BLOCKED,
                str(self.store.root),
                "Ensure local receipt storage is writable.",
                True,
                "candidate",
            ),
        ]
        migration = self.runner.run(
            "migration graph",
            ["python", "-m", "alembic", "-c", "server/alembic.ini", "heads"],
            cwd=self.root,
            timeout_class="tool",
        )
        diagnostics.append(
            Diagnostic(
                "migration graph",
                Status.PASS if migration.exit_code == 0 else Status.BLOCKED,
                migration.stdout or migration.stderr,
                migration.recommended_action,
                True,
                "candidate",
            )
        )
        web_bearing = (self.root / "web" / "package.json").is_file()
        if web_bearing:
            diagnostics.extend(
                [
                    self._tool("Node", ["node", "--version"], required=True, scope="candidate"),
                    self._tool(
                        "pnpm", [self._pnpm_command(), "--version"], required=True, scope="candidate", expected=self._pinned_pnpm()
                    ),
                    Diagnostic(
                        "frozen lockfile",
                        Status.PASS if (self.root / "web" / "pnpm-lock.yaml").is_file() else Status.BLOCKED,
                        "pnpm-lock.yaml present"
                        if (self.root / "web" / "pnpm-lock.yaml").is_file()
                        else "pnpm-lock.yaml absent",
                        "Restore the committed lockfile.",
                        True,
                        "candidate",
                    ),
                ]
            )
        ci = self._ci_status(state.commit)
        diagnostics.append(ci)
        if scope == "publication":
            diagnostics.extend(self._publication_diagnostics(state))
        relevant = [
            item for item in diagnostics if item.required and (item.scope == scope or item.scope == "candidate")
        ]
        blocked = [item for item in relevant if item.status in {Status.BLOCKED, Status.UNKNOWN, Status.NOT_RUN}]
        status = Status.BLOCKED if blocked else Status.PASS
        action = (
            "Resolve blocked required prerequisites."
            if blocked
            else (
                "Prepare an isolated candidate."
                if scope == "candidate"
                else "Publish only an exact retained candidate with explicit confirmation."
            )
        )
        return OperationResult(
            status,
            f"{scope.capitalize()} readiness evaluated.",
            action,
            tuple(diagnostics),
            {"repository": asdict(state), "scope": scope, "web_bearing": web_bearing},
        )

    def status(self) -> OperationResult:
        return self.readiness("candidate")

    def _storage_writable(self) -> bool:
        try:
            self.store.root.mkdir(parents=True, exist_ok=True)
            probe = self.store.root / ".write-probe"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return True
        except OSError:
            return False

    def _ci_status(self, commit: str) -> Diagnostic:
        if not shutil.which("gh"):
            return Diagnostic(
                "CI status",
                Status.NOT_RUN,
                "GitHub CLI is unavailable; CI status was not queried.",
                "Install/authenticate GitHub CLI to query CI.",
                False,
                "candidate",
            )
        result = self.runner.run(
            "CI status",
            ["gh", "run", "list", "--commit", commit, "--limit", "1", "--json", "status,conclusion"],
            cwd=self.root,
            timeout_class="github",
        )
        if result.exit_code:
            return Diagnostic(
                "CI status",
                Status.UNKNOWN,
                result.stderr or "CI status is unavailable",
                "Authenticate GitHub CLI or inspect CI directly.",
                False,
                "candidate",
            )
        try:
            runs = json.loads(result.stdout)
        except json.JSONDecodeError:
            return Diagnostic(
                "CI status",
                Status.UNKNOWN,
                "GitHub CLI returned malformed CI data",
                "Inspect GitHub Actions response.",
                False,
                "candidate",
            )
        if not runs:
            return Diagnostic(
                "CI status", Status.NOT_RUN, "No CI run exists for this commit.", None, False, "candidate"
            )
        run = runs[0]
        if run.get("status") != "completed":
            return Diagnostic(
                "CI status",
                Status.WARNING,
                f"CI is {run.get('status')}",
                "Wait for the matching CI run.",
                False,
                "candidate",
            )
        return Diagnostic(
            "CI status",
            Status.PASS if run.get("conclusion") == "success" else Status.BLOCKED,
            f"CI conclusion: {run.get('conclusion')}",
            "Inspect failed CI jobs." if run.get("conclusion") != "success" else None,
            False,
            "candidate",
        )

    def _publication_diagnostics(self, state: Any) -> list[Diagnostic]:
        diagnostics = [
            self._tool("GitHub CLI", ["gh", "--version"], required=True, scope="publication"),
            Diagnostic(
                "origin remote",
                Status.PASS if _remote_repository(self.root) else Status.BLOCKED,
                _remote_repository(self.root) or "origin is not a supported GitHub remote",
                "Configure a GitHub origin.",
                True,
                "publication",
            ),
        ]
        auth = self.runner.run("GitHub authentication", ["gh", "auth", "status"], cwd=self.root, timeout_class="github")
        diagnostics.append(
            Diagnostic(
                "GitHub authentication",
                Status.PASS if auth.exit_code == 0 else Status.BLOCKED,
                auth.stdout or auth.stderr,
                "Authenticate GitHub CLI.",
                True,
                "publication",
            )
        )
        pending = [
            item
            for item in self.store.list("publication")
            if item.get("state") not in {PublicationState.PUBLICATION_COMPLETE.value}
        ]
        diagnostics.append(
            Diagnostic(
                "unfinished publication",
                Status.BLOCKED if pending else Status.PASS,
                f"{len(pending)} unfinished publication transaction(s)",
                "Resume or reconcile the matching transaction." if pending else None,
                True,
                "publication",
            )
        )
        return diagnostics

    def _candidate(self, *, bump: str | None, explicit_version: str | None, persist: bool) -> CandidateRecord:
        if bool(bump) == bool(explicit_version):
            raise DeploymentError("specify exactly one candidate --bump or --version")
        readiness = self.readiness("candidate")
        if readiness.status is not Status.PASS:
            blockers = "; ".join(
                f"{item.name}: {item.detail}"
                for item in readiness.diagnostics
                if item.required and item.status in {Status.BLOCKED, Status.UNKNOWN, Status.NOT_RUN}
            )
            raise DeploymentError("candidate readiness is blocked" + (f": {blockers}" if blockers else ""))
        from release_tools.versioning import Version

        state = inspect_git_state(self.root)
        target = explicit_version or str(Version.parse(str(state.version)).bump(str(bump)))
        version = Version.parse(target)
        source_version = Version.parse(str(state.version))
        if version < source_version:
            raise DeploymentError("candidate version cannot be older than the governed source version")
        if version == source_version:
            # The single 0.24.0 product operation is already governed on this
            # branch.  Phase 1B-2 must build that exact committed tree, never
            # synthesize a second version/history bump just to make a candidate.
            # Stage exact candidate clones beneath the ignored receipt store
            # rather than the Windows user TEMP directory.  Besides keeping
            # all candidate mutation out of the canonical tree, this avoids
            # Windows 8.3 TEMP aliases which break Vite's virtual-module
            # resolution in the real web test suite.
            staging = self.store.root / "staging"
            staging.mkdir(parents=True, exist_ok=True)
            temporary = tempfile.TemporaryDirectory(prefix="eoat-release-candidate-", dir=staging)
            clone = Path(temporary.name) / "source"
            copied = subprocess.run(
                ["git", "clone", "--quiet", "--shared", str(self.root), str(clone)],
                text=True,
                capture_output=True,
                check=False,
            )
            if copied.returncode:
                temporary.cleanup()
                raise DeploymentError("could not create isolated exact candidate repository")
            commit = Git(clone).output("rev-parse", state.commit)
            checked_out = subprocess.run(["git", "checkout", "--quiet", "--detach", commit], cwd=clone, check=False)
            if checked_out.returncode:
                temporary.cleanup()
                raise DeploymentError("could not select exact governed candidate commit")
        else:
            temporary, clone, commit = _clone_for_dry_run(self.root, version)
        candidate_id = f"candidate-{target}-{commit[:12]}"
        try:
            checks, _commands = run_validation(clone)
            failures = [check for check in checks if check.status != CheckStatus.PASS]
            if failures:
                detail = "; ".join(f"{item.name}: {item.detail}" for item in failures)
                return CandidateRecord(
                    1,
                    candidate_id,
                    CandidateState.FAILED,
                    str(self.root),
                    state.branch,
                    state.commit,
                    commit,
                    None,
                    target,
                    f"v{target}",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    Status.NOT_RUN,
                    tuple(asdict(x) for x in checks),
                    next_action_for(CandidateState.FAILED),
                    detail,
                )
            timestamp = utc_now()
            first = self._build_candidate(clone, commit, state.branch, Path(temporary.name) / "first", timestamp)
            second = self._build_candidate(clone, commit, state.branch, Path(temporary.name) / "second", timestamp)
            deterministic = Status.PASS if sha256_file(first.archive) == sha256_file(second.archive) else Status.BLOCKED
            if deterministic is Status.BLOCKED:
                return CandidateRecord(
                    1,
                    candidate_id,
                    CandidateState.FAILED,
                    str(self.root),
                    state.branch,
                    state.commit,
                    commit,
                    None,
                    target,
                    f"v{target}",
                    first.archive.name,
                    first.external["artifact"]["sha256"],
                    sha256_file(first.manifest),
                    self._web_manifest_hash(first),
                    None,
                    None,
                    deterministic,
                    tuple(asdict(x) for x in checks),
                    next_action_for(CandidateState.FAILED),
                    "deterministic rebuild artifact hashes differ",
                )
            tree = Git(clone).output("rev-parse", f"{commit}^{{tree}}")
            artifact_path = bundle_path = None
            if persist:
                destination = self.store.root / "candidates" / candidate_id
                if destination.exists():
                    raise DeploymentError("candidate identity already exists locally; refusing overwrite")
                destination.mkdir(parents=True)
                server_destination = destination / "core" / "server"
                web_destination = destination / "core" / "web"
                server_destination.mkdir(parents=True)
                for item in (first.archive, first.checksum, first.manifest):
                    shutil.copy2(item, server_destination / item.name)
                web = first.archive.parent / "web-static"
                if web.is_dir():
                    shutil.copytree(web, web_destination / "static")
                    build_web_package(
                        web_destination / "static",
                        web_destination / f"eoat-atlas-web-{target}-{commit[:7]}.zip",
                    )
                bundle = destination / "source" / "candidate.bundle"
                bundle.parent.mkdir(parents=True)
                # A governed-version candidate can intentionally resolve to
                # the already committed source tip.  In that case excluding
                # ``state.commit`` would ask Git to create an empty bundle.
                # Retain the exact commit (and its history) instead; bundle
                # verification still proves the declared commit/tree and the
                # self-ancestry relation.
                bundle_revisions = [commit] if commit == state.commit else [commit, f"^{state.commit}"]
                bundle_result = subprocess.run(
                    ["git", "bundle", "create", str(bundle), *bundle_revisions],
                    cwd=clone,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if bundle_result.returncode:
                    raise DeploymentError("could not persist the exact candidate Git bundle")
                notes = self.root / "docs" / "release_notes" / f"EOAT_Atlas_{target}.md"
                copy_release_notes(notes, candidate_root=destination, version=str(target))
                artifact_path, bundle_path = str(server_destination / first.archive.name), str(bundle)
            return CandidateRecord(
                1,
                candidate_id,
                CandidateState.CANDIDATE_VALIDATED,
                str(self.root),
                state.branch,
                state.commit,
                commit,
                tree,
                target,
                f"v{target}",
                first.archive.name,
                first.external["artifact"]["sha256"],
                sha256_file(first.manifest),
                self._web_manifest_hash(first),
                artifact_path,
                bundle_path,
                deterministic,
                tuple(asdict(x) for x in checks),
                next_action_for(CandidateState.CANDIDATE_VALIDATED),
            )
        finally:
            temporary.cleanup()

    def _build_candidate(self, clone: Path, commit: str, branch: str, output: Path, timestamp: datetime) -> Any:
        web_static = output / "web-static" if (clone / "web" / "package.json").is_file() else None
        if web_static is not None:
            from deployment.web_release import build_web_static

            build_web_static(clone, commit, web_static)
        return build_deployment_archive(
            clone, commit, output, branch=branch, timestamp=timestamp, web_static=web_static
        )

    @staticmethod
    def _web_manifest_hash(build: Any) -> str | None:
        path = build.archive.parent / "web-static" / "web-static.manifest.json"
        return sha256_file(path) if path.is_file() else None

    def rehearse_candidate(self, bump: str | None = None, explicit_version: str | None = None) -> OperationResult:
        candidate = self._candidate(bump=bump, explicit_version=explicit_version, persist=False)
        return OperationResult(
            Status.PASS if candidate.state is CandidateState.CANDIDATE_VALIDATED else Status.BLOCKED,
            "Candidate rehearsal completed without canonical changes.",
            candidate.next_safe_action,
            data={"candidate": candidate, "dry_run": True},
        )

    def prepare_candidate(self, bump: str | None = None, explicit_version: str | None = None) -> OperationResult:
        candidate = self._candidate(bump=bump, explicit_version=explicit_version, persist=True)
        receipt = self._schema_two_candidate_receipt(candidate) if candidate.state is CandidateState.CANDIDATE_VALIDATED else self._serialize(candidate)
        path = self.store.write("candidate", candidate.candidate_id, receipt)
        return OperationResult(
            Status.PASS if candidate.state is CandidateState.CANDIDATE_VALIDATED else Status.BLOCKED,
            "Candidate prepared and validated."
            if candidate.state is CandidateState.CANDIDATE_VALIDATED
            else "Candidate validation failed.",
            candidate.next_safe_action,
            data={"candidate": candidate, "receipt_path": str(path)},
        )

    def _schema_two_candidate_receipt(self, candidate: CandidateRecord) -> dict[str, Any]:
        """Persist an unsigned working set; Phase 1B sealing is explicit."""

        if not candidate.artifact_path or not candidate.bundle_path or not candidate.candidate_tree or not candidate.candidate_commit:
            raise DeploymentError("validated candidate is missing immutable source or artifact paths")
        artifact = Path(candidate.artifact_path)
        directory = artifact.parent
        candidate_root = directory.parents[1] if directory.name == "server" and directory.parent.name == "core" else directory
        external = json.loads((directory / "release_manifest.json").read_text(encoding="utf-8"))
        core, _ = validate_external_manifest(external)
        identity = ProductReleaseIdentity(
            str(candidate.version), str(core["release_id"]), str(core["build_id"]), str(candidate.candidate_commit),
            str(candidate.candidate_tree), str(candidate.branch), "candidate", str(core["created_at_utc"]), candidate.candidate_id,
        )
        def item(
            kind: ComponentKind,
            disposition: ArtifactDisposition,
            *,
            path: Path | None = None,
            reason: str = "",
            metadata: dict[str, str] | None = None,
            media_type: str = "application/octet-stream",
        ) -> ReleaseSetComponent:
            return ReleaseSetComponent(
                kind, disposition, identity.product_version, identity.release_id, identity.build_id, identity.source_commit,
                identity.source_tree, identity.candidate_id, artifact_filename=path.name if path else "",
                artifact_locator=candidate_locator(candidate_root, path) if path else "", size_bytes=path.stat().st_size if path else 0,
                sha256=sha256_file(path) if path else "", media_type=media_type if path else "",
                validation_status=ComponentValidation.PASS if path else (ComponentValidation.NOT_APPLICABLE if disposition is ArtifactDisposition.NOT_APPLICABLE else ComponentValidation.NOT_RUN),
                not_applicable_justification=reason,
                metadata=metadata or {},
            )
        web_package = candidate_root / "core" / "web" / f"eoat-atlas-web-{candidate.version}-{candidate.candidate_commit[:7]}.zip"
        web_manifest = candidate_root / "core" / "web" / "static" / "web-static.manifest.json"
        notes = candidate_root / "core" / "release-notes" / f"EOAT-Atlas-{candidate.version}-release-notes.md"
        components = []
        for kind in ComponentKind:
            if kind is ComponentKind.SERVER:
                components.append(item(kind, ArtifactDisposition.BUILT, path=artifact, metadata={
                    "external_manifest_locator": candidate_locator(candidate_root, directory / "release_manifest.json"),
                    "checksum_locator": candidate_locator(candidate_root, directory / f"{artifact.name}.sha256"),
                }, media_type="application/gzip"))
            elif kind is ComponentKind.WEB and web_package.is_file():
                components.append(item(kind, ArtifactDisposition.BUILT, path=web_package, metadata={
                    "file_manifest_locator": candidate_locator(candidate_root, web_manifest),
                }, media_type="application/zip"))
            elif kind is ComponentKind.SOURCE_BUNDLE:
                components.append(item(kind, ArtifactDisposition.BUILT, path=Path(candidate.bundle_path), media_type="application/x-git-bundle"))
            elif kind is ComponentKind.RELEASE_NOTES and notes.is_file():
                components.append(item(kind, ArtifactDisposition.BUILT, path=notes, media_type="text/markdown"))
            elif kind in {ComponentKind.RELEASE_SET_MANIFEST, ComponentKind.RELEASE_SET_SIGNATURE}:
                components.append(item(kind, ArtifactDisposition.PENDING, reason="Created only by explicit final release-set sealing."))
            elif kind in {ComponentKind.BOOTSTRAP, ComponentKind.BOOTSTRAP_UPDATE_MANIFEST}:
                components.append(
                    item(
                        kind,
                        ArtifactDisposition.NOT_APPLICABLE,
                        reason="Bootstrap implementation is owned by Unified Release Train Phase 2.",
                    )
                )
            else:
                components.append(item(kind, ArtifactDisposition.PENDING, reason="Required platform artifact is pending validated Windows build attachment."))
        release_set = SignedReleaseSet(
            identity, tuple(components), str(core["api_contract_version"]), str(core["database"]["target_revision"]),
            "UNKNOWN", "0.0.0", "0.0.0", "0.0.0", ("server archive validated",),
        )
        raw = self._serialize(candidate)
        raw.update({
            "schema_version": 2, "state": "PLATFORM_ARTIFACTS_PENDING", "working_release_set": release_set.unsigned_dict(),
            "release_set": None, "bundle_sha256": sha256_file(Path(candidate.bundle_path)), "publication_eligible": False,
            "blocking_reasons": ["Desktop and launcher artifacts require validated Windows CI attachment."],
            "next_safe_action": "Attach validated Windows platform artifacts, then seal the release set.",
        })
        return raw

    @staticmethod
    def _serialize(value: Any) -> dict[str, Any]:
        raw = asdict(value)
        for key, item in list(raw.items()):
            if hasattr(item, "value"):
                raw[key] = item.value
        return raw

    def candidate(self, candidate_id: str) -> dict[str, Any]:
        return self.store.read("candidate", candidate_id)

    def build_core_artifacts(self, candidate_id: str) -> OperationResult:
        """Re-validate retained immutable core artifacts and record evidence.

        Candidate preparation creates the bytes in an isolated clone.  This
        operation deliberately does not rebuild them from the operator's
        checkout; it proves the retained files and their exact source bundle
        before a Windows attachment can be accepted.
        """

        receipt = self.store.candidate_representation(candidate_id)
        if receipt.get("receipt_compatibility") != "SCHEMA_2_UNSIGNED":
            raise DeploymentError("core artifact construction requires an unsigned schema-2 candidate")
        root = self.store.root / "candidates" / candidate_id
        server = root / "core" / "server"
        archive = Path(str(receipt.get("artifact_path") or ""))
        if archive.parent != server:
            raise DeploymentError("candidate server artifact is outside its immutable core directory")
        validate_deployment_archive(archive, server / "release_manifest.json", server / f"{archive.name}.sha256")
        web = root / "core" / "web"
        packages = sorted(web.glob("eoat-atlas-web-*.zip"))
        if len(packages) != 1:
            raise DeploymentError("candidate must contain exactly one immutable web package")
        validate_web_package(packages[0])
        bundle = Path(str(receipt["bundle_path"]))
        verified_bundle = verify_source_bundle(
            bundle,
            candidate_root=root,
            commit=str(receipt["candidate_commit"]),
            tree=str(receipt["candidate_tree"]),
            base_commit=str(receipt["base_commit"]),
            repository=self.root,
        )
        notes = root / "core" / "release-notes" / f"EOAT-Atlas-{receipt['version']}-release-notes.md"
        copied_notes = copy_release_notes(
            self.root / "docs" / "release_notes" / f"EOAT_Atlas_{receipt['version']}.md",
            candidate_root=root,
            version=str(receipt["version"]),
        )
        if copied_notes.path != notes:
            raise DeploymentError("candidate release notes locator is not deterministic")
        working = dict(receipt["working_release_set"])
        components = list(working.get("components") or [])
        evidence = {
            "server": sha256_file(archive),
            "web": sha256_file(packages[0]),
            "source_bundle": verified_bundle.sha256,
            "release_notes": copied_notes.sha256,
        }
        for component in components:
            if component.get("kind") in evidence:
                component["validation_status"] = "PASS"
                metadata = dict(component.get("metadata") or {})
                metadata["core_validation_sha256"] = evidence[str(component["kind"])]
                if component.get("kind") == "source_bundle":
                    metadata["verification_receipt_locator"] = candidate_locator(root, verified_bundle.manifest_path or bundle)
                component["metadata"] = metadata
        working["components"] = components
        receipt["working_release_set"] = working
        receipt["core_artifacts_verified_at_utc"] = utc_text()
        receipt["next_safe_action"] = "Attach validated Windows platform artifacts, then complete Phase 1B-3 sealing."
        path = self.store.write("candidate", candidate_id, receipt)
        return OperationResult(Status.PASS, "Retained core artifacts were validated from exact candidate identity.", receipt["next_safe_action"], data={"receipt_path": str(path), "evidence": evidence})

    def verify_core_artifacts(self, candidate_id: str) -> OperationResult:
        return self.build_core_artifacts(candidate_id)

    def inspect_platform_attachment(self, candidate_id: str, attachment_path: Path) -> OperationResult:
        candidate = self.store.candidate_representation(candidate_id)
        if candidate.get("receipt_compatibility") != "SCHEMA_2_UNSIGNED":
            raise DeploymentError("platform attachment inspection requires an unsigned schema-2 candidate")
        info = inspect_attachment(attachment_path, candidate)
        return OperationResult(
            Status.PASS,
            "Windows platform attachment identity and artifact inventory are valid.",
            "Attach the validated platform artifact bundle.",
            data={"attachment": info["manifest"], "components": [item.kind for item in info["components"]]},
        )

    def attach_platform_artifacts(self, candidate_id: str, attachment_path: Path) -> OperationResult:
        candidate = self.store.candidate_representation(candidate_id)
        if candidate.get("receipt_compatibility") != "SCHEMA_2_UNSIGNED" or candidate.get("state") != "PLATFORM_ARTIFACTS_PENDING":
            raise DeploymentError("platform artifacts may only attach to an unsigned platform-pending candidate")
        candidate_root = self.store.root / "candidates" / candidate_id
        result = attach_platform_artifacts(candidate_root, candidate, attachment_path)
        receipt_path = self.store.write("candidate", candidate_id, result["candidate"])
        attachment_receipt = write_attachment_receipt(
            candidate_root,
            candidate_id=candidate_id,
            manifest=result["attachment"],
            components=result["components"],
        )
        view = self.store.candidate_representation(candidate_id)
        return OperationResult(
            Status.PASS,
            "Windows platform artifacts were attached to the exact unsigned candidate.",
            str(view["next_safe_action"]),
            data={"receipt_path": str(receipt_path), "attachment_receipt": str(attachment_receipt), "missing_components": view["missing_components"]},
        )

    def verify_platform_artifacts(self, candidate_id: str) -> OperationResult:
        candidate = self.store.candidate_representation(candidate_id)
        if candidate.get("receipt_compatibility") != "SCHEMA_2_UNSIGNED":
            raise DeploymentError("platform verification requires an unsigned schema-2 candidate")
        working = candidate.get("working_release_set") or {}
        components = {str(item.get("kind")): item for item in working.get("components", []) if isinstance(item, dict)}
        required = {ComponentKind.DESKTOP.value, ComponentKind.DESKTOP_UPDATE_MANIFEST.value, ComponentKind.LAUNCHER.value, ComponentKind.LAUNCHER_UPDATE_MANIFEST.value}
        blocked = sorted(kind for kind in required if components.get(kind, {}).get("validation_status") != "PASS")
        if blocked:
            return OperationResult(Status.BLOCKED, "Platform artifact verification is incomplete.", "Attach a validated Windows artifact bundle.", data={"blocking_components": blocked})
        return OperationResult(Status.PASS, "Attached Windows platform artifacts remain identity-valid.", str(candidate.get("next_safe_action")), data={"missing_components": candidate["missing_components"]})

    def candidates(self) -> OperationResult:
        return OperationResult(
            Status.PASS,
            "Retained candidate inventory loaded.",
            "Select a candidate to inspect or publish.",
            data={"candidates": self.store.list("candidate")},
        )

    def discard_candidate(self, candidate_id: str) -> OperationResult:
        self.store.discard_candidate(candidate_id)
        return OperationResult(
            Status.PASS,
            "Unpromoted candidate was discarded locally.",
            "Prepare a new candidate when needed.",
            data={"candidate_id": candidate_id},
        )

    def _candidate_identity(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.store.candidate_representation(candidate_id)
        if candidate.get("receipt_compatibility") != "SCHEMA_2":
            raise DeploymentError("legacy schema-1 candidates cannot enter unified release-set publication")
        required = (
            "candidate_commit",
            "candidate_tree",
            "artifact_sha256",
            "manifest_sha256",
            "artifact_path",
            "bundle_path",
        )
        if candidate.get("state") != CandidateState.CANDIDATE_VALIDATED.value or any(
            not candidate.get(key) for key in required
        ):
            raise DeploymentError("candidate receipt is not a complete validated immutable candidate")
        artifact = Path(str(candidate["artifact_path"]))
        manifest = artifact.parent / "release_manifest.json"
        if (
            not artifact.is_file()
            or not manifest.is_file()
            or sha256_file(artifact) != candidate["artifact_sha256"]
            or sha256_file(manifest) != candidate["manifest_sha256"]
        ):
            raise DeploymentError("candidate artifact or manifest identity no longer matches its receipt")
        return candidate

    def publish_start(
        self, candidate_id: str, confirmation: str, *, publisher: Publisher | None = None
    ) -> OperationResult:
        candidate = self._candidate_identity(candidate_id)
        if confirmation != candidate["version"]:
            raise DeploymentError("publication confirmation must exactly match the candidate version")
        publication_id = f"publication-{candidate_id}"
        if (self.store.root / "publication" / f"{publication_id}.json").is_file():
            return self.publish_resume(publication_id, publisher=publisher)
        record = PublicationRecord(
            1,
            publication_id,
            candidate_id,
            PublicationState.CANDIDATE_VALIDATED,
            str(candidate["version"]),
            str(candidate["tag"]),
            str(candidate["candidate_commit"]),
            str(candidate["candidate_tree"]),
            str(candidate["artifact_sha256"]),
            str(candidate["manifest_sha256"]),
            (),
            next_action_for(PublicationState.CANDIDATE_VALIDATED),
        )
        self.store.write("publication", publication_id, self._serialize(record))
        return self.publish_resume(publication_id, publisher=publisher)

    def publish(self, candidate_id: str, confirmation: str, *, publisher: Publisher | None = None) -> OperationResult:
        """Compatibility alias for the former single publication command."""
        return self.publish_start(candidate_id, confirmation, publisher=publisher)

    def publish_resume(self, publication_id: str, *, publisher: Publisher | None = None) -> OperationResult:
        record = self.store.read("publication", publication_id)
        candidate = self._candidate_identity(str(record.get("candidate_id")))
        if any(
            record.get(field) != candidate.get(field)
            for field in ("candidate_commit", "candidate_tree", "artifact_sha256", "manifest_sha256")
        ):
            raise DeploymentError("publication and candidate identities disagree")
        execution = publisher or SubprocessPublisher(self.root, self.runner)
        completed = list(record.get("completed_steps", []))
        steps = (
            (PublicationState.RELEASE_COMMIT_CREATED, "promote"),
            (PublicationState.TAG_CREATED, "ensure_tag"),
            (PublicationState.BRANCH_PUSHED, "push_branch"),
            (PublicationState.TAG_PUSHED, "push_tag"),
            (PublicationState.GITHUB_RELEASE_CREATED, "ensure_release"),
            (PublicationState.PRIMARY_ASSETS_UPLOADED, "upload_assets"),
            (PublicationState.RECEIPT_ATTACHED, "attach_receipt"),
        )
        current = PublicationState(record.get("state", PublicationState.CANDIDATE_VALIDATED.value))
        try:
            for state, method in steps:
                receipt_for_verify = dict(record)
                if state.value in completed:
                    if not execution.verify_step(candidate, state, receipt_for_verify):
                        raise DeploymentError(
                            f"completed publication step {state.value} no longer matches candidate identity"
                        )
                    continue
                if current is not PublicationState.CANDIDATE_VALIDATED:
                    require_transition(current, state)
                if state is PublicationState.RECEIPT_ATTACHED:
                    receipt_path = self.store.write("publication", publication_id, record)
                    execution.attach_receipt(candidate, receipt_path)
                else:
                    getattr(execution, method)(candidate)
                if not execution.verify_step(candidate, state, record):
                    raise DeploymentError(
                        f"publication step {state.value} completed without independent identity verification"
                    )
                current = state
                completed.append(state.value)
                record.update(
                    {
                        "state": current.value,
                        "completed_steps": completed,
                        "next_safe_action": next_action_for(current),
                        "failure": None,
                    }
                )
                self.store.write("publication", publication_id, record)
            record.update(
                {
                    "state": PublicationState.PUBLICATION_COMPLETE.value,
                    "completed_steps": [*completed, PublicationState.PUBLICATION_COMPLETE.value],
                    "next_safe_action": next_action_for(PublicationState.PUBLICATION_COMPLETE),
                }
            )
            path = self.store.write("publication", publication_id, record)
            return OperationResult(
                Status.PASS,
                "Publication transaction completed and reconciled.",
                record["next_safe_action"],
                data={"publication": record, "receipt_path": str(path)},
            )
        except (DeploymentError, OSError, ValueError) as exc:
            record.update(
                {
                    "state": PublicationState.FAILED_RECOVERABLE.value,
                    "next_safe_action": next_action_for(PublicationState.FAILED_RECOVERABLE),
                    "failure": redact_text(str(exc)),
                    "retryable": True,
                }
            )
            path = self.store.write("publication", publication_id, record)
            return OperationResult(
                Status.BLOCKED,
                "Publication stopped without unsafe rollback.",
                record["next_safe_action"],
                (Diagnostic("publication", Status.BLOCKED, record["failure"]),),
                {"publication": record, "receipt_path": str(path)},
            )

    def publication(self, publication_id: str) -> OperationResult:
        record = self.store.read("publication", publication_id)
        return OperationResult(
            Status.PASS if record.get("state") == PublicationState.PUBLICATION_COMPLETE.value else Status.BLOCKED,
            "Publication receipt loaded.",
            str(record.get("next_safe_action", "Review publication receipt.")),
            data={"publication": record},
        )

    def inventory(self) -> OperationResult:
        try:
            releases = github_releases(self.root)
        except DeploymentError as exc:
            return OperationResult(
                Status.BLOCKED,
                "GitHub release inventory unavailable.",
                "Configure GitHub CLI authentication, then refresh inventory.",
                (Diagnostic("GitHub Releases", Status.BLOCKED, str(exc)),),
            )
        inventory = [self._inventory_item(item) for item in releases]
        return OperationResult(
            Status.PASS,
            f"{len(inventory)} release(s) discovered.",
            "Select and verify an eligible release before planning deployment.",
            data={"releases": inventory},
        )

    @staticmethod
    def _inventory_item(release: GitHubRelease) -> dict[str, Any]:
        assets = {asset.name for asset in release.assets}
        archives = sorted(name for name in assets if name.endswith(".tar.gz"))
        reasons: list[str] = []
        if release.draft:
            reasons.append("draft release")
        if release.prerelease:
            reasons.append("prerelease")
        if len(archives) != 1:
            reasons.append("exactly one server archive is required")
        elif "release_manifest.json" not in assets or f"{archives[0]}.sha256" not in assets:
            reasons.append("manifest or checksum asset is missing")
        return {
            "version": str(release.version),
            "tag": release.tag,
            "commit": None,
            "release_id": None,
            "build_id": None,
            "published_at": release.published_at,
            "draft": release.draft,
            "prerelease": release.prerelease,
            "assets": sorted(assets),
            "manifest_status": "NOT_RUN",
            "artifact_status": "NOT_RUN",
            "tag_status": "NOT_RUN",
            "schema_target": None,
            "deployable": not reasons,
            "blocking_reasons": reasons,
        }

    def verify_release(self, version: str, cache_root: Path | None = None) -> OperationResult:
        cache = cache_root or self.store.root / "release-cache"
        release = select_release(github_releases(self.root), version)
        directory = cache_release(self.root, release, cache)
        release_dir, external = _local_release(directory)
        core, artifact = validate_external_manifest(external)
        validate_deployment_archive(
            release_dir / artifact["filename"],
            release_dir / "release_manifest.json",
            release_dir / f"{artifact['filename']}.sha256",
        )
        tag_commit = release_tag_commit(self.root, release, core)
        if tag_commit != core["commit_sha"]:
            raise DeploymentError("Git tag commit does not match release manifest commit")
        payload = {
            "version": str(core["version"]),
            "tag": release.tag,
            "release": asdict(manifest_identity(core)),
            "artifact": artifact,
            "cache_path": str(release_dir),
            "tag_status": "PASS",
            "manifest_status": "PASS",
            "artifact_status": "PASS",
            "schema_target": core["database"]["target_revision"],
        }
        path = self.store.write(
            "inspection",
            f"release-{version}",
            {
                "state": "RELEASE_VERIFIED",
                "next_safe_action": "Run target inspection before deployment planning.",
                **payload,
            },
        )
        return OperationResult(
            Status.PASS,
            "Selected release was fully verified.",
            "Run read-only target inspection before deployment planning.",
            data={**payload, "receipt_path": str(path)},
        )

    def inspect_target(self, config_path: Path) -> OperationResult:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if raw.get("test_target") is not True:
            raise DeploymentError("target inspection requires an explicit non-production test_target configuration")
        config = load_server_config(config_path.resolve())
        if config.hostname.casefold() in _PRODUCTION_HOSTS:
            raise DeploymentError("production target hostnames are prohibited by convergence tooling")
        inspection = inspect_server_only(config)
        try:
            from deployment.active_deployment import PrivilegedHelperClient

            envelope = validate_diagnostic_envelope(PrivilegedHelperClient(config).invoke(diagnostic_request()))
            diagnostic = Diagnostic(
                "diagnostic method",
                Status.PASS,
                "Versioned structured helper diagnostic was verified.",
                required=True,
                scope="target",
            )
        except DeploymentError:
            envelope = fallback_envelope(inspection, config.hostname)
            diagnostic = Diagnostic(
                "diagnostic method",
                Status.WARNING,
                "Compatibility allowlisted SSH fallback is in use.",
                required=False,
                scope="target",
            )
        payload = {
            "state": "TARGET_INSPECTED",
            "next_safe_action": "Verify a selected release and create a deployment plan.",
            "target_name": config.hostname,
            "diagnostic_method": envelope.method,
            "facts": envelope.facts,
            "unavailable": envelope.unavailable,
            "blocking_failures": inspection.get("blocking_failures", []),
            "warnings": inspection.get("warnings", []),
        }
        identifier = f"inspection-{utc_text().replace(':', '').replace('-', '')}"
        path = self.store.write("inspection", identifier, payload)
        status = (
            Status.BLOCKED if payload["blocking_failures"] else Status.WARNING if payload["warnings"] else Status.PASS
        )
        return OperationResult(
            status,
            "Read-only target inspection completed.",
            payload["next_safe_action"],
            (diagnostic,),
            {**payload, "inspection_id": identifier, "receipt_path": str(path)},
        )

    def create_plan(self, version: str, inspection_id: str) -> OperationResult:
        release_record = self.store.read("inspection", f"release-{version}")
        inspection = self.store.read("inspection", inspection_id)
        facts = inspection.get("facts", {})
        target_schema = release_record.get("schema_target")
        source_schema = facts.get("schema_revision")
        helper = facts.get("helper", {}) if isinstance(facts, dict) else {}
        capabilities = set(helper.get("operations", [])) if isinstance(helper, dict) else set()
        recovery = bool(facts.get("transactions")) if isinstance(facts, dict) else False
        mode = self._plan_mode(source_schema, target_schema, capabilities, recovery)
        plan_id = f"plan-{version}-{inspection_id.removeprefix('inspection-')}"
        warnings = tuple(inspection.get("warnings", []))
        blockers = tuple(inspection.get("blocking_failures", []))
        if mode is DeploymentMode.MIGRATION_BLOCKED:
            blockers = (*blockers, "migration helper capability is incomplete")
        if mode is DeploymentMode.MIGRATION_STATE_UNKNOWN:
            blockers = (*blockers, "target schema is unknown")
        plan = DeploymentPlan(
            1,
            plan_id,
            mode,
            version,
            str(release_record["release"]["commit_sha"]),
            release_record["release"]["release_id"],
            release_record["release"]["build_id"],
            source_schema,
            target_schema,
            inspection.get("target_name"),
            blockers,
            warnings,
            tuple(sorted(capabilities)),
            ("upload artifact", "stage release", "activate API", "activate web", "restart services")
            if mode is DeploymentMode.NO_MIGRATION_REQUIRED
            else (
                "verify backup",
                "stage release",
                "migrate database",
                "activate API",
                "activate web",
                "restart services",
            ),
            "Application rollback restores API/web only; database restoration is explicit and separately verified.",
            next_action_for(mode),
        )
        path = self.store.write("plan", plan_id, self._serialize(plan))
        return OperationResult(
            Status.BLOCKED if blockers else Status.PASS,
            "Deployment plan created from stored release and target facts.",
            plan.next_safe_action,
            data={"plan": plan, "receipt_path": str(path)},
        )

    @staticmethod
    def _plan_mode(
        source_schema: str | None, target_schema: str | None, capabilities: set[str], recovery: bool
    ) -> DeploymentMode:
        if recovery:
            return DeploymentMode.ROLLBACK_OR_RECOVERY_REQUIRED
        if not source_schema or not target_schema:
            return DeploymentMode.MIGRATION_STATE_UNKNOWN
        if source_schema == target_schema:
            return DeploymentMode.NO_MIGRATION_REQUIRED
        required = {"backup-production", "verify-backup", "apply-migration", "verify-migration"}
        return DeploymentMode.MIGRATION_REQUIRED if required <= capabilities else DeploymentMode.MIGRATION_BLOCKED

    def deployment_plan(
        self,
        *,
        version: str,
        commit: str,
        source_schema: str | None,
        target_schema: str | None,
        helper_capabilities: set[str] | None = None,
        recovery_required: bool = False,
    ) -> DeploymentPlan:
        """Compatibility constructor; normal flows use stored release/target facts."""
        capabilities = helper_capabilities or set()
        mode = (
            DeploymentMode.ROLLBACK_OR_RECOVERY_REQUIRED
            if recovery_required
            else self._plan_mode(source_schema, target_schema, capabilities, False)
        )
        blockers: tuple[str, ...] = ()
        if mode is DeploymentMode.MIGRATION_STATE_UNKNOWN:
            blockers = ("source or target schema is unknown",)
        elif mode is DeploymentMode.MIGRATION_BLOCKED:
            blockers = ("installed helper does not prove required migration and backup capabilities",)
        return DeploymentPlan(
            1,
            f"diagnostic-plan-{version}",
            mode,
            version,
            commit,
            None,
            None,
            source_schema,
            target_schema,
            None,
            blockers,
            (),
            tuple(sorted(capabilities)),
            (),
            "Application rollback and database restore are separate operations.",
            next_action_for(mode),
        )

    def plan(self, plan_id: str) -> OperationResult:
        plan = self.store.read("plan", plan_id)
        return OperationResult(
            Status.BLOCKED if plan.get("blocking_reasons") else Status.PASS,
            "Deployment plan loaded.",
            str(plan.get("next_safe_action")),
            data={"plan": plan},
        )

    def begin_transaction(self, plan_id: str, confirmation: str) -> OperationResult:
        plan = self.store.read("plan", plan_id)
        if confirmation != plan.get("selected_version"):
            raise DeploymentError("staging confirmation must exactly match the selected version")
        if plan.get("blocking_reasons"):
            raise DeploymentError("blocked deployment plan cannot start a transaction")
        identifier = f"transaction-{plan_id.removeprefix('plan-')}"
        transaction = DeploymentTransaction(
            1,
            identifier,
            plan_id,
            DeploymentState.NOT_STARTED,
            str(plan["selected_version"]),
            str(plan["selected_commit"]),
            plan.get("release_id"),
            plan.get("build_id"),
            None,
            plan.get("source_schema"),
            plan.get("target_schema"),
            DeploymentMode(plan["mode"]),
            plan.get("target_name"),
            None,
            tuple(plan.get("required_capabilities", [])),
            (),
            None,
            None,
            None,
            None,
            None,
            next_action_for(DeploymentState.NOT_STARTED),
            True,
            {"production": False, "api": False, "web": False, "database": False},
            {},
        )
        path = self.store.write("transaction", identifier, self._serialize(transaction))
        return OperationResult(
            Status.PASS,
            "Deployment transaction initialized; no target mutation occurred.",
            transaction.next_safe_action,
            data={"transaction": transaction, "receipt_path": str(path)},
        )

    def transition_transaction(
        self, transaction_id: str, target: DeploymentState, confirmation: str | None = None
    ) -> OperationResult:
        record = self.store.read("transaction", transaction_id)
        current = DeploymentState(record["state"])
        mode = DeploymentMode(record["migration_mode"])
        dangerous = {
            DeploymentState.ACTIVATION_STARTED,
            DeploymentState.MIGRATION_APPROVED,
            DeploymentState.ROLLBACK_STARTED,
            DeploymentState.DATABASE_RESTORE_STARTED,
        }
        if target in dangerous and confirmation != transaction_id:
            raise DeploymentError("dangerous transaction action requires typing the exact transaction ID")
        validate_deployment_transition(current, target, mode)
        record["state"] = target.value
        record["completed_states"] = [*record.get("completed_states", []), target.value]
        record["next_safe_action"] = next_action_for(target)
        path = self.store.write("transaction", transaction_id, record)
        return OperationResult(
            Status.PASS,
            f"Transaction advanced to {target.value}.",
            record["next_safe_action"],
            data={"transaction": record, "receipt_path": str(path)},
        )

    def transaction(self, transaction_id: str) -> OperationResult:
        record = self.store.read("transaction", transaction_id)
        return OperationResult(
            Status.PASS,
            "Deployment transaction loaded.",
            str(record.get("next_safe_action")),
            data={"transaction": record},
        )

    def receipts(self) -> OperationResult:
        return OperationResult(
            Status.PASS,
            "Receipt inventory loaded.",
            "Select a receipt to review or export.",
            data={"receipts": self.store.list_all(), "quarantine": self.store.quarantine()},
        )

    def receipt(self, identifier: str) -> OperationResult:
        kind, record = self.store.find(identifier)
        return OperationResult(
            Status.PASS,
            f"{kind.capitalize()} receipt loaded.",
            str(record.get("next_safe_action", "Review receipt.")),
            data={"kind": kind, "receipt": record},
        )

    def export_receipt(self, identifier: str, output: Path) -> OperationResult:
        path = self.store.export_text(identifier, output)
        return OperationResult(
            Status.PASS,
            "Human-readable receipt exported.",
            "Retain the export with the transaction evidence.",
            data={"path": str(path)},
        )
