"""Builds the release ZIP for plugins.qgis.org: dev/dist/GeoFA-<version>.zip, with the folder geofa/.

    python-qgis.bat tools/build_zip.py
    python-qgis.bat tools/build_zip.py --folder <plugins folder>   (the same files, unpacked, as <folder>/geofa)

The ZIP holds geofa_plugin's files minus what isn't part of the plugin (RELEASE_EXCLUDES; the
package tests use release_files() too). The files are checked for secrets first, and nothing is
written if one is found: the password and token values in geofa_plugin/.env (never printed), and
anything that looks like a password or token being set. This is a quick check of what ships;
tools/secret_scan.py checks the whole history with broader patterns.
"""
import argparse
import configparser
import fnmatch
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "geofa_plugin"
FOLDER = "geofa"  # the plugin's folder in QGIS, as in earlier versions
# Not part of the plugin: tests, the guide's images (the guide is read on GitHub), and hidden files
# such as .env, .gitattributes and .gitignore. plugins.qgis.org turns down hidden files and compiled Python.
RELEASE_EXCLUDES = ("test", "Vejledning", "__pycache__", "*.pyc", ".*")
SECRET = re.compile(r"(?i)\b(password|passwd|token|api_?key|secret)\b['\"]?\s*[=:]\s*['\"][^'\"\s]{4,}['\"]")
TEXT = (".py", ".txt", ".json", ".qml", ".md", ".ui", ".xml", ".cfg", ".svg")


def release_files():
    """The plugin's files that go into the ZIP, in a fixed order."""
    return [path for path in sorted(PLUGIN.rglob("*")) if path.is_file()
            and not any(fnmatch.fnmatch(part, pattern) for part in path.relative_to(PLUGIN).parts
                        for pattern in RELEASE_EXCLUDES)]


def env_secrets():
    """{key: value} for the passwords and tokens in geofa_plugin/.env (the username isn't secret)."""
    path = PLUGIN / ".env"
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
             if "=" in line and not line.lstrip().startswith("#"))
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs
            if re.search(r"(?i)pass|token|key|secret", key) and len(value.strip().strip("'\"")) >= 4}


def problems(files):
    """What would leak, without the values: ["path: why", ...]."""
    found, secrets = [], env_secrets()
    for path in files:
        if path.suffix.lower() not in TEXT:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.relative_to(PLUGIN).as_posix()
        match = SECRET.search(text)
        if match:
            found.append(f"{name}: sets a {match.group(1).lower()}")
        found += [f"{name}: holds the value of {key} from .env" for key, value in secrets.items() if value in text]
    return found


def install(folder, files):
    """The release files, unpacked as <folder>/geofa (replaced if it's there), e.g. in a QGIS profile's plugins."""
    target = Path(folder) / FOLDER
    shutil.rmtree(target, ignore_errors=True)
    for path in files:
        destination = target / path.relative_to(PLUGIN)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    print(f"{target}: {len(files)} files")


def main():
    parser = argparse.ArgumentParser(description="Build the release ZIP, or install its files unpacked.")
    parser.add_argument("--folder", help="install the release files unpacked as <folder>/geofa instead")
    args = parser.parse_args()
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(PLUGIN / "metadata.txt", encoding="utf-8")
    version = metadata["general"]["version"]
    files = release_files()
    found = problems(files)
    if found:
        print("Not built, as these would leak:", *found, sep="\n  ")
        return 1
    if args.folder:
        install(args.folder, files)
        return 0
    unusual = [p.relative_to(PLUGIN).as_posix() for p in files if not p.relative_to(PLUGIN).as_posix().isascii()]
    if unusual:
        print("Note: file names with non-ASCII characters (check that plugins.qgis.org accepts them):",
              *unusual, sep="\n  ")
    out = REPO / "dev" / "dist" / f"GeoFA-{version}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        for path in files:
            package.write(path, f"{FOLDER}/{path.relative_to(PLUGIN).as_posix()}")
    print(f"{out}: version {version}, {len(files)} files, {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
