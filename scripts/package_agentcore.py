"""Build a Linux ARM64 AgentCore code artifact locally; does not deploy or call AWS."""

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    args = parser.parse_args()
    build = ROOT / "build" / args.provider
    build.mkdir(parents=True, exist_ok=True)
    requirements = build / "requirements.txt"
    subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--extra",
            args.provider,
            "--extra",
            "agentcore",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    package = build / "package"
    if package.exists():
        shutil.rmtree(package)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python-platform",
            "aarch64-manylinux_2_28",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--target",
            str(package),
            "-r",
            str(requirements),
        ],
        check=True,
    )
    for source, target in [
        (ROOT / "src/strands_connect", package / "strands_connect"),
        (ROOT / "examples", package / "examples"),
    ]:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".env", ".env.*"))
    example = "connect_openai_realtime" if args.provider == "openai" else "connect_gemini"
    (package / "entrypoint.py").write_text(
        f'from examples.{example}.app import app\napp.run(log_level="info")\n'
    )
    artifact = build / "agentcore.zip"
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(package))
    print(artifact)


if __name__ == "__main__":
    main()
