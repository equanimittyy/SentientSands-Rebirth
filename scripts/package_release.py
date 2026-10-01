"""Build the Sentient Sands release zip.

The zip holds everything a player needs: the mod files, the built plugin DLL, the
Python server, and an embedded Windows Python runtime with the server
dependencies already installed. Players do not install Python or run pip. The
plugin starts server\\python\\python.exe when it exists (plugin/core/Utils.cpp).

Runs on any OS with Python 3 and pip: pip fetches Windows wheels with --platform.
"""
import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MOD_NAME = "SentientSands"
SERVER_DIRS = ("scripts", "config", "templates")
DEFAULT_PYTHON = "3.13.3"


def read_mod_version():
    for line in (REPO / "mod" / "mod.info").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "version":
            return value.strip()
    raise SystemExit("mod/mod.info has no version= line")


def stage_files(stage, dll):
    # Skip what local test runs leave behind; the DLL comes from --dll instead.
    shutil.copytree(REPO / "mod", stage, ignore=shutil.ignore_patterns("*.dll", "*.log", "sentient_sands_registry"))
    # Copy named folders only, so logs and campaigns from a local server run stay out.
    for name in SERVER_DIRS:
        shutil.copytree(
            REPO / "server" / name,
            stage / "server" / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copy2(dll, stage / "SentientSands.dll")


def fetch_embedded_python(version, cache):
    name = f"python-{version}-embed-amd64.zip"
    path = cache / name
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        url = f"https://www.python.org/ftp/python/{version}/{name}"
        print(f"Downloading {url}")
        partial = path.with_name(name + ".part")
        urllib.request.urlretrieve(url, partial)
        partial.replace(path)
    return path


def install_python(embed_zip, version, python_dir):
    with zipfile.ZipFile(embed_zip) as archive:
        archive.extractall(python_dir)
    # The ._pth file fixes sys.path for the embedded runtime. The shipped one
    # leaves out Lib\site-packages, so flask would fail to import.
    tag = "".join(version.split(".")[:2])
    pth = python_dir / f"python{tag}._pth"
    if not pth.exists():
        raise SystemExit(f"{embed_zip.name} has no {pth.name}")
    pth.write_text(f"python{tag}.zip\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")


def install_dependencies(version, site_packages):
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--requirement", str(REPO / "server" / "requirements.txt"),
            "--target", str(site_packages),
            "--platform", "win_amd64",
            "--python-version", ".".join(version.split(".")[:2]),
            "--implementation", "cp",
            "--only-binary=:all:",
            "--no-compile",
            "--disable-pip-version-check",
        ],
        check=True,
    )
    shutil.rmtree(site_packages / "bin", ignore_errors=True)


def make_zip(stage, out_zip):
    out_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            archive.write(path, path.relative_to(stage.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dll", required=True, type=Path, help="path to the built SentientSands.dll")
    parser.add_argument("--python-version", default=DEFAULT_PYTHON, help=f"embedded Python version (default {DEFAULT_PYTHON})")
    parser.add_argument("--out", type=Path, default=REPO / "dist", help="output directory (default dist/)")
    args = parser.parse_args()

    if not args.dll.is_file():
        raise SystemExit(f"DLL not found: {args.dll}")

    stage_root = args.out / "stage"
    shutil.rmtree(stage_root, ignore_errors=True)
    stage = stage_root / MOD_NAME
    stage_files(stage, args.dll)

    python_dir = stage / "server" / "python"
    embed_zip = fetch_embedded_python(args.python_version, args.out / "cache")
    install_python(embed_zip, args.python_version, python_dir)
    install_dependencies(args.python_version, python_dir / "Lib" / "site-packages")

    out_zip = args.out / f"{MOD_NAME}-{read_mod_version()}.zip"
    make_zip(stage, out_zip)
    print(f"Wrote {out_zip}")


if __name__ == "__main__":
    main()
