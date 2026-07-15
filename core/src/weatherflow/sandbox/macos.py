import asyncio
import math
import os
import signal
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from weatherflow.sandbox.models import SandboxLimits, SandboxRequest, SandboxResult

SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
DYLD_PROFILE = Path("/System/Library/Sandbox/Profiles/dyld-support.sb")

SYSTEM_READ_ROOTS = (
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/Library/Apple",
    "/Library/Developer",
    "/opt/homebrew",
    "/usr/local",
    "/private/etc",
    "/private/var/db/timezone",
    "/private/var/select",
)

RESOURCE_LAUNCH_SCRIPT = """
set -eu
cpu_limit="$1"
file_blocks="$2"
open_files="$3"
shift 3
ulimit -t "$cpu_limit"
ulimit -f "$file_blocks"
ulimit -n "$open_files"
exec "$@"
""".strip()

_HEALTH_PROBE_CACHE: dict[tuple[str, str], bool] = {}


class SandboxUnavailableError(RuntimeError):
    pass


class SandboxTimeoutError(TimeoutError):
    pass


class MacOSSeatbeltStdioProcess:
    def __init__(
        self,
        process: asyncio.subprocess.Process,
        temporary_home: tempfile.TemporaryDirectory[str],
    ) -> None:
        self.process = process
        self.temporary_home = temporary_home
        self._closed = False

    @property
    def stdin(self) -> asyncio.StreamWriter | None:
        return self.process.stdin

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        return self.process.stdout

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await _terminate_process_group(self.process)
        finally:
            await asyncio.to_thread(self.temporary_home.cleanup)


class MacOSSeatbeltSandbox:
    backend_id = "macos-seatbelt-v1"

    def __init__(
        self,
        *,
        executable: Path = SANDBOX_EXECUTABLE,
        dyld_profile: Path = DYLD_PROFILE,
    ) -> None:
        self.executable = executable
        self.dyld_profile = dyld_profile

    def is_available(self) -> bool:
        cached_health = _HEALTH_PROBE_CACHE.get((str(self.executable), str(self.dyld_profile)))
        return (
            sys.platform == "darwin"
            and not os.environ.get("WF_SANDBOX_ACTIVE")
            and cached_health is not False
            and self.executable.is_file()
            and os.access(self.executable, os.X_OK)
            and self.dyld_profile.is_file()
        )

    async def health_probe(self) -> bool:
        key = (str(self.executable), str(self.dyld_profile))
        cached = _HEALTH_PROBE_CACHE.get(key)
        if cached is not None:
            return cached
        if not self.is_available() or os.environ.get("WF_SANDBOX_ACTIVE"):
            _HEALTH_PROBE_CACHE[key] = False
            return False
        temporary = await asyncio.to_thread(
            tempfile.TemporaryDirectory,
            prefix="wf-sandbox-probe-",
        )
        try:
            workspace, secret, escaped, script = await asyncio.to_thread(
                _prepare_health_probe,
                Path(temporary.name),
            )
            result = await self.execute(
                SandboxRequest(
                    argv=("/bin/sh", str(script), str(secret), str(escaped)),
                    cwd=str(workspace),
                    readable_roots=(str(workspace),),
                    writable_roots=(str(workspace),),
                    environment={"PATH": "/usr/bin:/bin"},
                    limits=SandboxLimits(
                        wall_time_seconds=5,
                        cpu_time_seconds=5,
                        max_file_size_bytes=1024**2,
                        max_open_files=64,
                        max_output_bytes=4096,
                    ),
                )
            )
            healthy = result.returncode == 0 and not await asyncio.to_thread(escaped.exists)
        except Exception:
            healthy = False
        finally:
            await asyncio.to_thread(temporary.cleanup)
        _HEALTH_PROBE_CACHE[key] = healthy
        return healthy

    def compile_profile(
        self,
        request: SandboxRequest,
        *,
        sandbox_home: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        parameters: dict[str, str] = {
            "SANDBOX_HOME": str(Path(sandbox_home or request.cwd).resolve())
        }
        readable_parameters: list[str] = []
        for index, root in enumerate(request.readable_roots):
            name = f"READ_ROOT_{index}"
            parameters[name] = root
            readable_parameters.append(name)
        writable_parameters: list[str] = []
        for index, root in enumerate(request.writable_roots):
            name = f"WRITE_ROOT_{index}"
            parameters[name] = root
            writable_parameters.append(name)

        system_filters = " ".join(f'(subpath "{root}")' for root in SYSTEM_READ_ROOTS)
        readable_filters = " ".join(f'(subpath (param "{name}"))' for name in readable_parameters)
        ancestor_filters = " ".join(
            f'(path-ancestors (param "{name}"))' for name in [*readable_parameters, "SANDBOX_HOME"]
        )
        writable_filters = " ".join(f'(subpath (param "{name}"))' for name in writable_parameters)
        if request.network.value == "loopback":
            network_rules = """
(allow network-bind network-inbound
  (local ip "localhost:*"))
(allow network-outbound
  (remote ip "localhost:*"))
""".strip()
        elif request.network.value == "https_egress":
            network_rules = """
(deny network-outbound
  (remote ip "localhost:*"))
(allow network-outbound
  (remote tcp "*:443")
  (literal "/private/var/run/mDNSResponder"))
""".strip()
        else:
            network_rules = ""
        profile = f"""
(version 1)
(deny default)
(import "dyld-support.sb")
(allow mach-bootstrap)
(allow syscall*)
(deny syscall-unix
  (syscall-number SYS_setsid SYS_setpgid))
(allow mach-register (local-name-prefix ""))
(allow process-exec process-fork)
(allow signal (target self))
(allow signal (target children))
(allow process-info* (target self))
(allow sysctl-read)
{network_rules}
(allow network-bind network-inbound
  (subpath (param "SANDBOX_HOME"))
  {writable_filters})
(allow network-outbound
  (subpath (param "SANDBOX_HOME"))
  {writable_filters})
(allow file-read* file-test-existence file-map-executable
  {system_filters}
  {readable_filters}
  (subpath (param "SANDBOX_HOME")))
(allow file-read-metadata file-test-existence
  (literal "/")
  (literal "/etc")
  (literal "/tmp")
  (literal "/var")
  {ancestor_filters})
(allow file-read* file-test-existence file-write-data
  (literal "/dev/null")
  (literal "/dev/zero"))
(allow file-read* file-test-existence
  (literal "/dev/random")
  (literal "/dev/urandom"))
(allow file-read-data file-test-existence file-write-data
  (subpath "/dev/fd"))
(allow file-write*
  (subpath (param "SANDBOX_HOME"))
  {writable_filters})
""".strip()
        return profile, parameters

    async def execute(self, request: SandboxRequest) -> SandboxResult:
        started_at = time.monotonic()
        process, temporary_home = await self._spawn_process(
            request,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_task = asyncio.create_task(
                _read_bounded(process.stdout, request.limits.max_output_bytes)
            )
            stderr_task = asyncio.create_task(
                _read_bounded(process.stderr, request.limits.max_output_bytes)
            )
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=request.limits.wall_time_seconds,
                )
            except TimeoutError:
                await asyncio.shield(_kill_process_group(process))
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise SandboxTimeoutError(
                    f"sandbox exceeded {request.limits.wall_time_seconds:g}s wall limit"
                ) from None
            except asyncio.CancelledError:
                await asyncio.shield(_kill_process_group(process))
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                raise

            stdout, stdout_truncated = await stdout_task
            stderr, stderr_truncated = await stderr_task
        finally:
            await asyncio.to_thread(temporary_home.cleanup)
        return SandboxResult(
            backend_id=self.backend_id,
            argv=request.argv,
            returncode=process.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            duration_ms=max(0, round((time.monotonic() - started_at) * 1000)),
            network=request.network,
        )

    async def spawn_stdio(self, request: SandboxRequest) -> MacOSSeatbeltStdioProcess:
        process, temporary_home = await self._spawn_process(
            request,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return MacOSSeatbeltStdioProcess(process, temporary_home)

    async def _spawn_process(
        self,
        request: SandboxRequest,
        *,
        stdin: int,
        stdout: int,
        stderr: int,
    ) -> tuple[asyncio.subprocess.Process, tempfile.TemporaryDirectory[str]]:
        if not self.is_available():
            raise SandboxUnavailableError("macOS Seatbelt sandbox is unavailable")
        _require_runtime_paths(request)
        temporary_home = tempfile.TemporaryDirectory(prefix="wf-sb-")
        try:
            resolved_home = await asyncio.to_thread(os.path.realpath, temporary_home.name)
            profile, parameters = self.compile_profile(
                request,
                sandbox_home=resolved_home,
            )
            command = [str(self.executable), "-p", profile]
            for name, value in sorted(parameters.items()):
                command.extend(("-D", f"{name}={value}"))
            command.extend(request.argv)
            cargo_home = await asyncio.to_thread(
                _prepare_private_cargo_home,
                request.environment,
                resolved_home,
                request.readable_roots,
            )
            environment = _sandbox_environment(
                request.environment,
                resolved_home,
                cargo_home=cargo_home,
            )
            launch_command = _resource_launch_command(command, request.limits)
            process = await asyncio.create_subprocess_exec(
                *launch_command,
                cwd=request.cwd,
                env=environment,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        except BaseException:
            await asyncio.to_thread(temporary_home.cleanup)
            raise
        return process, temporary_home


def _require_runtime_paths(request: SandboxRequest) -> None:
    cwd = Path(request.cwd)
    if not cwd.is_dir():
        raise ValueError("sandbox working directory is missing or not a directory")
    for root in request.readable_roots:
        if not Path(root).exists():
            raise ValueError("sandbox readable root is missing")
    for root in request.writable_roots:
        if not Path(root).is_dir():
            raise ValueError("sandbox writable root is missing or not a directory")


def _prepare_health_probe(root: Path) -> tuple[Path, Path, Path, Path]:
    workspace = root / "workspace"
    workspace.mkdir()
    secret = root / "outside-secret.txt"
    secret.write_text("sandbox-probe-secret")
    escaped = root / "outside-write.txt"
    script = workspace / "probe.sh"
    script.write_text(
        "#!/bin/sh\n"
        'if cat "$1" >/dev/null 2>&1; then exit 91; fi\n'
        'if touch "$2" >/dev/null 2>&1; then exit 92; fi\n'
        "exit 0\n"
    )
    script.chmod(0o700)
    return workspace, secret, escaped, script


def _sandbox_environment(
    source: Mapping[str, str],
    sandbox_home: str,
    *,
    cargo_home: str | None = None,
) -> dict[str, str]:
    environment = dict(source)
    environment.setdefault("PATH", "/usr/bin:/bin")
    environment.update(
        {
            "HOME": sandbox_home,
            "CARGO_HOME": cargo_home or str(Path(sandbox_home) / ".cargo"),
            "CARGO_NET_OFFLINE": "true",
            "TMPDIR": sandbox_home,
            "TMP": sandbox_home,
            "TEMP": sandbox_home,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "NPM_CONFIG_USERCONFIG": os.devnull,
            "PIP_CONFIG_FILE": os.devnull,
            "PYTHONNOUSERSITE": "1",
            "WF_SANDBOX_ACTIVE": MacOSSeatbeltSandbox.backend_id,
        }
    )
    return environment


def _prepare_private_cargo_home(
    source: Mapping[str, str],
    sandbox_home: str,
    readable_roots: tuple[str, ...],
) -> str:
    private_home = Path(sandbox_home) / ".cargo"
    private_home.mkdir(mode=0o700)
    configured_home = source.get("CARGO_HOME")
    if not configured_home:
        return str(private_home)
    source_home = Path(configured_home)
    if not source_home.is_absolute() or source_home.name != ".cargo":
        return str(private_home)
    readable = tuple(Path(root) for root in readable_roots)
    for name in ("registry", "git"):
        source_cache = source_home / name
        try:
            resolved_cache = source_cache.resolve()
            allowed = source_cache.is_dir() and any(
                resolved_cache == root or resolved_cache.is_relative_to(root) for root in readable
            )
        except OSError:
            allowed = False
        if allowed:
            (private_home / name).symlink_to(resolved_cache, target_is_directory=True)
    return str(private_home)


def _resource_launch_command(command: list[str], limits: SandboxLimits) -> list[str]:
    return [
        "/bin/sh",
        "-c",
        RESOURCE_LAUNCH_SCRIPT,
        "weatherflow-sandbox-launcher",
        str(max(1, int(limits.cpu_time_seconds))),
        str(max(1, math.ceil(limits.max_file_size_bytes / 512))),
        str(limits.max_open_files),
        *command,
    ]


async def _read_bounded(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    captured = 0
    truncated = False
    while chunk := await stream.read(65_536):
        remaining = limit - captured
        if remaining > 0:
            kept = chunk[:remaining]
            chunks.append(kept)
            captured += len(kept)
        if len(chunk) > max(remaining, 0):
            truncated = True
    return b"".join(chunks), truncated


async def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await process.wait()


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            await _kill_process_group(process)
            return
    await process.wait()
