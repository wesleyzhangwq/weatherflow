#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TAURI = ROOT / "desktop" / "src-tauri"
OUTPUT = ROOT / "release" / "macos"
VERSION = "3.0.0-alpha.1"


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


def dependencies() -> list[dict[str, Any]]:
    values: dict[tuple[str, str, str], dict[str, Any]] = {}
    for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]:
        key = ("pypi", package["name"], package["version"])
        values[key] = {"ecosystem": key[0], "name": key[1], "version": key[2]}
    node = json.loads((ROOT / "desktop" / "package-lock.json").read_text())
    for path, package in node.get("packages", {}).items():
        if not path or "version" not in package:
            continue
        name = package.get("name") or path.rsplit("node_modules/", 1)[-1]
        key = ("npm", name, package["version"])
        values[key] = {
            "ecosystem": key[0],
            "name": key[1],
            "version": key[2],
            "license": package.get("license", "SEE_UPSTREAM"),
        }
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


def signing_state(app: Path, dmg: Path) -> str:
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
    blocker = OUTPUT / "SIGNING_BLOCKER.md"
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
            "--deep",
            "--options",
            "runtime",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sidecar", action="store_true")
    args = parser.parse_args()
    if not args.skip_sidecar:
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
    toolchain = Path(
        subprocess.run(
            ["rustup", "which", "cargo"], text=True, capture_output=True, check=True
        ).stdout.strip()
    ).parent
    environment = {**os.environ, "PATH": f"{toolchain}:{os.environ['PATH']}"}
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
    bundle = TAURI / "target" / "aarch64-apple-darwin" / "release" / "bundle"
    source_app = next((bundle / "macos").glob("*.app"))
    shutil.rmtree(OUTPUT, ignore_errors=True)
    OUTPUT.mkdir(parents=True)
    app = OUTPUT / "WeatherFlow.app"
    dmg = OUTPUT / f"WeatherFlow_{VERSION}_aarch64.dmg"
    shutil.copytree(source_app, app, symlinks=True)
    inspect_app(app)
    run(["python3", "tools/release/smoke_app.py", str(app)])
    create_dmg(app, dmg)
    state = signing_state(app, dmg)
    run(["python3", "tools/release/smoke_app.py", str(app)])
    components = dependencies()
    (OUTPUT / "sbom.json").write_text(
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
    (OUTPUT / "THIRD_PARTY_LICENSES.json").write_text(
        json.dumps(components, indent=2, sort_keys=True) + "\n"
    )
    checksum_targets = [
        dmg,
        app / "Contents" / "Info.plist",
        next(
            path
            for path in (app / "Contents" / "MacOS").iterdir()
            if "weatherflow-core" in path.name
        ),
        OUTPUT / "sbom.json",
        OUTPUT / "THIRD_PARTY_LICENSES.json",
    ]
    (OUTPUT / "CHECKSUMS.sha256").write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(OUTPUT)}\n" for path in checksum_targets
        )
    )
    (OUTPUT / "release-status.json").write_text(
        json.dumps(
            {"version": VERSION, "architecture": "arm64", "signing": state}, indent=2
        )
        + "\n"
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
