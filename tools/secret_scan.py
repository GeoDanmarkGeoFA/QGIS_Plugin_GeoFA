"""Scan every file version in git history (and files inside zip/qgz) for credentials. Prints no secret values.

    python tools/secret_scan.py [repo] [--git PATH] [--branch main]

Plain Python is enough. Give --git where git isn't on the PATH, as in OSGeo4W's shell. Paths that
still exist on --branch are marked [on main]; the match may be in an older version of the file.
This is the full check before a release; tools/build_zip.py only checks the files it packs.
"""
import argparse
import io
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict

PATTERNS = {
    "password value": re.compile(r"(?i)\b(password|passwd|pwd|adgangskode)\b['\"]?\s*[=:]\s*['\"]([^'\"\s]{3,})['\"]"),
    "password in URI": re.compile(r"(?i)\bpassword=([^'\"\s&]{3,})"),
    "login in URL": re.compile(r"https?://[^/\s:@'\"]+:([^/\s@'\"]+)@"),
    "token/key": re.compile(r"(?i)\b(token|api[_-]?key|secret|client_secret)\b['\"]?\s*[=:]\s*['\"]([A-Za-z0-9_\-\.]{8,})['\"]"),
    "token in URL": re.compile(
        r"(?i)(?:[?&;]|%3F|%26)(?:amp;)?(token|apikey|api_key|key|access_token|password|pw)(?:=|%3D|%253D)([^&'\"\s<%]{6,})"),
    "known token format": re.compile(r"(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]{10,})"),
    "Basic auth header": re.compile(r"Basic\s+([A-Za-z0-9+/=]{12,})"),
    "kom login name": re.compile(r"\b(kom\d{3})\b"),
}
CODE_LIKE = re.compile(r"^[A-Za-z_][\w\.]*(\(.*\))?$")


def scan(text, where, hits):
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            value = m.group(m.lastindex or 0)
            if kind == "kom login name":
                shown = value
            elif CODE_LIKE.match(value) and ("." in value or "(" in value):
                shown = f"code: {value}"
            else:
                shown = f"<{len(value)} chars hidden>"
            hits.add((where, kind, shown))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--git", default=shutil.which("git") or "git", help="the git program (default: from the PATH)")
    parser.add_argument("--branch", default="main", help="mark paths that still exist on this branch")
    args = parser.parse_args()

    def git(*command, data=None):
        return subprocess.run([args.git, "-C", args.repo, *command], input=data, capture_output=True, check=True).stdout

    # blob sha -> paths it appeared under; and which paths exist on the branch today
    paths = defaultdict(set)
    for line in git("rev-list", "--all", "--objects").decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            paths[sha].add(path)
    on_branch = set(git("ls-tree", "-r", "--name-only", args.branch).decode("utf-8", "replace").splitlines())
    types = git("cat-file", "--batch-check=%(objectname) %(objecttype)", data="\n".join(paths).encode()).decode().splitlines()
    blobs = [t.split()[0] for t in types if t.endswith(" blob")]

    hits = set()
    batch = git("cat-file", "--batch", data="\n".join(blobs).encode())
    pos = 0
    while pos < len(batch):
        header_end = batch.index(b"\n", pos)
        sha, _, size = batch[pos:header_end].decode().split()
        content = batch[header_end + 1: header_end + 1 + int(size)]
        pos = header_end + 1 + int(size) + 1
        where = " | ".join(sorted(paths[sha]))
        if content[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for member in zf.namelist():
                        if not member.endswith("/"):
                            scan(zf.read(member).decode("latin-1"), f"{where} :: {member}", hits)
            except zipfile.BadZipFile:
                pass
            continue
        scan(content.decode("latin-1"), where, hits)

    by_kind = defaultdict(list)
    for where, kind, shown in sorted(hits):
        present = any(p in on_branch for p in where.split(" :: ")[0].split(" | "))
        by_kind[kind].append(f"{f'[on {args.branch}] ' if present else '[history] '}{where} -> {shown}")
    for kind in PATTERNS:
        print(f"== {kind}: {len(by_kind[kind])}")
        for line in by_kind[kind][:40]:
            print("  ", line)
    print("blobs scanned:", len(blobs))


if __name__ == "__main__":
    main()
