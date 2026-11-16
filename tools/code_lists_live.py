"""Can every code list in the catalogue be read from GeoFA, as the plugin reads it?

    python-qgis.bat tools/code_lists_live.py [production|test|both]

Reads each distinct code list once (anonymous, read-only SQL API) and writes
dev/reports/code_lists_live.json: per list, the number of codes or why it failed, and
which datasets use it. Run before a release to see whether GeoFA has moved or broken a list.
"""
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geofa_plugin.catalogue import Catalogue  # noqa: E402
from geofa_plugin.codelists import CodeListError, parse  # noqa: E402
from geofa_plugin.loader import PRODUCTION_HOST, TEST_HOST  # noqa: E402

HOSTS = {"production": PRODUCTION_HOST, "test": TEST_HOST}


def read(host, source):
    try:
        with urllib.request.urlopen(source.url(host), timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        data = error.read()  # GeoFA answers SQL errors with HTTP 500 and a JSON message
    except Exception as error:  # noqa: BLE001 - reported
        return None, f"no answer: {error}"
    try:
        return len(parse(data)), None
    except CodeListError as problem:
        return None, str(problem)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    hosts = HOSTS if which == "both" else {which: HOSTS[which]}
    used = {}
    for dataset in Catalogue().datasets():
        for field, source, _ in dataset.code_lists:
            used.setdefault(source, []).append(f"{dataset.code}:{field}" + (" (pending)" if dataset.pending else ""))
    jobs = [(env, host, source) for env, host in hosts.items() for source in used]
    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = list(pool.map(lambda job: read(job[1], job[2]), jobs))
    report, failed = [], []
    for (env, _, source), (count, problem) in zip(jobs, answers):
        entry = {"environment": env, "table": source.table, "value": source.value, "text": source.text,
                 "where": source.where, "codes": count, "problem": problem, "used_by": used[source]}
        report.append(entry)
        if problem:
            failed.append(entry)
    out = ROOT / "dev" / "reports" / "code_lists_live.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(used)} code lists, {len(jobs)} reads, {len(failed)} failed -> {out}")
    for entry in failed:
        print(f"  {entry['environment']}: {entry['table']} ({entry['value']}/{entry['text']}): {entry['problem']} "
              f"- used by {', '.join(entry['used_by'][:6])}{' …' if len(entry['used_by']) > 6 else ''}")


if __name__ == "__main__":
    main()
