#!/usr/bin/env python3
import hashlib
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TAURI = ROOT / "desktop" / "src-tauri"
OUTPUT = ROOT / "release" / "macos"
STAGING = ROOT / "release" / ".weatherflow-release-staging"
RELEASE_LOCK = ROOT / "release" / ".weatherflow-release.lock"
VERSION = "3.0.0-alpha.1"
RELEASE_SOURCE_INPUTS = (
    Path("Makefile"),
    Path("package.json"),
    Path("pnpm-lock.yaml"),
    Path("pnpm-workspace.yaml"),
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("core/pyproject.toml"),
    Path("core/src/weatherflow"),
    Path("desktop/index.html"),
    Path("desktop/package.json"),
    Path("desktop/src"),
    Path("desktop/tsconfig.app.json"),
    Path("desktop/tsconfig.json"),
    Path("desktop/tsconfig.node.json"),
    Path("desktop/vite.config.ts"),
    Path("desktop/src-tauri/Cargo.lock"),
    Path("desktop/src-tauri/Cargo.toml"),
    Path("desktop/src-tauri/Entitlements.plist"),
    Path("desktop/src-tauri/Info.plist"),
    Path("desktop/src-tauri/build.rs"),
    Path("desktop/src-tauri/capabilities"),
    Path("desktop/src-tauri/icons"),
    Path("desktop/src-tauri/src"),
    Path("desktop/src-tauri/tauri.conf.json"),
    Path("tools/release"),
)


def run(
    command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_source_digest(root: Path) -> str:
    """Fingerprint every source input used to build the canonical release."""
    digest = hashlib.sha256()
    files: list[Path] = []
    for relative in RELEASE_SOURCE_INPUTS:
        candidate = root / relative
        if candidate.is_dir():
            files.extend(
                path
                for path in candidate.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
                and path.name != ".DS_Store"
            )
        elif candidate.is_file():
            files.append(candidate)
    for path in sorted(set(files)):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def require_unchanged_release_sources(root: Path, expected_digest: str) -> None:
    if release_source_digest(root) != expected_digest:
        raise SystemExit(
            "sources changed during the release build; discard it and rebuild"
        )


@contextmanager
def exclusive_release_lock():
    RELEASE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with RELEASE_LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def publish_staged_release(staging: Path, output: Path) -> None:
    """Transactionally replace the canonical directory after validation."""
    previous = output.parent / f".{output.name}.previous"
    shutil.rmtree(previous, ignore_errors=True)
    if output.exists():
        output.rename(previous)
    try:
        staging.rename(output)
    except BaseException:
        if previous.exists() and not output.exists():
            previous.rename(output)
        raise
    shutil.rmtree(previous, ignore_errors=True)


def dependencies() -> list[dict[str, Any]]:
    values: dict[tuple[str, str, str], dict[str, Any]] = {}
    for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]:
        key = ("pypi", package["name"], package["version"])
        values[key] = {"ecosystem": key[0], "name": key[1], "version": key[2]}
    inventory = json.loads(
        subprocess.run(
            [
                "pnpm",
                "list",
                "--filter",
                "weatherflow-desktop",
                "--depth",
                "Infinity",
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    def collect_node_packages(package: dict[str, Any]) -> None:
        for group in ("dependencies", "devDependencies", "optionalDependencies"):
            children = package.get(group, {})
            if not isinstance(children, dict):
                continue
            for name, child in children.items():
                if not isinstance(child, dict):
                    continue
                version = child.get("version")
                if isinstance(version, str):
                    key = ("npm", name, version)
                    values[key] = {
                        "ecosystem": key[0],
                        "name": key[1],
                        "version": key[2],
                        "license": "SEE_UPSTREAM",
                    }
                collect_node_packages(child)

    if not isinstance(inventory, list):
        raise SystemExit("pnpm returned an invalid dependency inventory")
    for workspace in inventory:
        if isinstance(workspace, dict):
            collect_node_packages(workspace)
    cargo = tomllib.loads((TAURI / "Cargo.lock").read_text())
    for package in cargo["package"]:
        key = ("cargo", package["name"], package["version"])
        values[key] = {"ecosystem": key[0], "name": key[1], "version": key[2]}
    return [values[key] for key in sorted(values)]


def inspect_app(app: Path) -> None:
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    expected = {
        "CFBundleIdentifier": "ai.weatherflow.desktop",
        "LSMinimumSystemVersion": "13.0",
    }
    for key, value in expected.items():
        if plist.get(key) != value:
            raise SystemExit(f"bundle metadata mismatch: {key}={plist.get(key)!r}")
    binaries = [
        path
        for path in (app / "Contents" / "MacOS").iterdir()
        if path.is_file() and os.access(path, os.X_OK)
    ]
    if not any("weatherflow-core" in path.name for path in binaries):
        raise SystemExit("bundle has no executable WeatherFlow sidecar")
    for binary in binaries:
        description = subprocess.run(
            ["file", str(binary)], text=True, capture_output=True, check=True
        ).stdout
        if "arm64" not in description:
            raise SystemExit(f"non-arm64 bundle executable: {description.strip()}")
        strings = subprocess.run(
            ["strings", str(binary)], text=True, capture_output=True, check=True
        ).stdout
        if str(ROOT) in strings or re.search(
            r"/Users/[^/]+/Projects/WeatherFlow", strings
        ):
            raise SystemExit(f"build path leaked into {binary.name}")


def validate_bundled_sidecar(app: Path) -> None:
    run(
        [
            "python3",
            "tools/release/test_desktop_sidecar.py",
            str(app / "Contents" / "MacOS" / "weatherflow-core"),
        ]
    )


def validate_app_smoke(app: Path) -> None:
    command = ["python3", "tools/release/smoke_app.py", str(app)]
    for attempt in range(2):
        try:
            run(command)
            return
        except subprocess.CalledProcessError:
            if attempt == 1:
                raise


def create_dmg(app: Path, dmg: Path) -> None:
    dmg.unlink(missing_ok=True)
    run(
        [
            "hdiutil",
            "create",
            "-volname",
            "WeatherFlow",
            "-srcfolder",
            str(app),
            "-ov",
            "-format",
            "UDZO",
            str(dmg),
        ]
    )


def signing_state(app: Path, dmg: Path, *, output: Path | None = None) -> str:
    output = OUTPUT if output is None else output
    identities = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        text=True,
        capture_output=True,
        check=False,
    ).stdout
    match = re.search(r'"(Developer ID Application: [^"]+)"', identities)
    required = ("APPLE_ID", "APPLE_PASSWORD", "APPLE_TEAM_ID")
    if match and all(os.environ.get(name) for name in required):
        identity = match.group(1)
        run(
            [
                "codesign",
                "--force",
                "--deep",
                "--options",
                "runtime",
                "--entitlements",
                str(TAURI / "Entitlements.plist"),
                "--sign",
                identity,
                str(app),
            ]
        )
        run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
        create_dmg(app, dmg)
        run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(dmg),
                "--apple-id",
                os.environ["APPLE_ID"],
                "--password",
                os.environ["APPLE_PASSWORD"],
                "--team-id",
                os.environ["APPLE_TEAM_ID"],
                "--wait",
            ]
        )
        run(["xcrun", "stapler", "staple", str(dmg)])
        return "signed_and_notarized"
    blocker = output / "SIGNING_BLOCKER.md"
    blocker.write_text(
        "# Apple signing blocker\n\n"
        "Unsigned release validation is complete. Signing and notarization require "
        "a Developer ID Application identity plus APPLE_ID, APPLE_PASSWORD, and "
        "APPLE_TEAM_ID in the release environment. No verification was weakened.\n"
    )
    run(
        [
            "codesign",
            "--force",
            "--entitlements",
            str(TAURI / "Entitlements.plist"),
            "--sign",
            "-",
            str(app),
        ]
    )
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    create_dmg(app, dmg)
    return "adhoc_unsigned_credentials_missing"


def build_release() -> int:
    expected_source_digest = release_source_digest(ROOT)
    run(
        [
            "uv",
            "run",
            "--package",
            "weatherflow-core",
            "--extra",
            "release",
            "python",
            "tools/release/build_sidecar.py",
        ]
    )
    run(
        [
            "python3",
            "tools/release/test_sidecar.py",
            "desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin",
        ]
    )
    run(
        [
            "python3",
            "tools/release/test_desktop_sidecar.py",
            "desktop/src-tauri/binaries/weatherflow-core-aarch64-apple-darwin",
        ]
    )
    toolchain = Path(
        subprocess.run(
            ["rustup", "which", "cargo"], text=True, capture_output=True, check=True
        ).stdout.strip()
    ).parent
    environment = {**os.environ, "PATH": f"{toolchain}:{os.environ['PATH']}"}
    bundle_macos = (
        TAURI / "target" / "aarch64-apple-darwin" / "release" / "bundle" / "macos"
    )
    shutil.rmtree(bundle_macos, ignore_errors=True)
    run(
        [
            "npx",
            "tauri",
            "build",
            "--target",
            "aarch64-apple-darwin",
            "--bundles",
            "app",
        ],
        cwd=ROOT / "desktop",
        env=environment,
    )
    source_app = bundle_macos / "WeatherFlow.app"
    built_apps = sorted(bundle_macos.glob("*.app"))
    if built_apps != [source_app] or not source_app.is_dir():
        raise SystemExit(f"unexpected Tauri app bundles: {built_apps}")
    shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True)
    app = STAGING / "WeatherFlow.app"
    dmg = STAGING / f"WeatherFlow_{VERSION}_aarch64.dmg"
    shutil.copytree(source_app, app, symlinks=True)
    inspect_app(app)
    validate_app_smoke(app)
    create_dmg(app, dmg)
    state = signing_state(app, dmg, output=STAGING)
    validate_bundled_sidecar(app)
    validate_app_smoke(app)
    components = dependencies()
    (STAGING / "sbom.json").write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "metadata": {"component": {"name": "WeatherFlow", "version": VERSION}},
                "components": components,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (STAGING / "THIRD_PARTY_LICENSES.json").write_text(
        json.dumps(components, indent=2, sort_keys=True) + "\n"
    )
    plist_path = app / "Contents" / "Info.plist"
    bundle_metadata = plistlib.loads(plist_path.read_bytes())
    gui = app / "Contents" / "MacOS" / bundle_metadata["CFBundleExecutable"]
    sidecar = next(
        path
        for path in (app / "Contents" / "MacOS").iterdir()
        if "weatherflow-core" in path.name
    )
    require_unchanged_release_sources(ROOT, expected_source_digest)
    (STAGING / "release-status.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "architecture": "arm64",
                "signing": state,
                "source_digest": expected_source_digest,
                "gui_sha256": sha256(gui),
                "sidecar_sha256": sha256(sidecar),
            },
            indent=2,
        )
        + "\n"
    )
    checksum_targets = [
        dmg,
        plist_path,
        gui,
        sidecar,
        STAGING / "sbom.json",
        STAGING / "THIRD_PARTY_LICENSES.json",
        STAGING / "release-status.json",
    ]
    (STAGING / "CHECKSUMS.sha256").write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(STAGING)}\n"
            for path in checksum_targets
        )
    )
    publish_staged_release(STAGING, OUTPUT)
    print(OUTPUT)
    return 0


def main() -> int:
    with exclusive_release_lock():
        return build_release()


if __name__ == "__main__":
    raise SystemExit(main())
