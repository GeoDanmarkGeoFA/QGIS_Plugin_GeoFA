# -*- coding: utf-8 -*-
"""GeoFA's code lists (the fkg.d_* tables) in the layers' dropdowns.

The styles hold no code lists. When the plugin adds a layer, and when a project is opened,
it reads each field's code list from GeoFA's SQL API (anonymous, read-only): the same
tables and columns GeoFA's own webmap uses for its dropdowns. If a list can't be read or
looks wrong, the field shows the codes instead, and the user is told which source failed.
"""
import functools
import json
import urllib.parse
from dataclasses import dataclass

from qgis.core import QgsApplication, QgsBlockingNetworkRequest, QgsEditorWidgetSetup, QgsFeedback, QgsSettings, QgsTask
from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest

SQL_PATH = "/api/v2/sql/fkg"
# Lists that failed and were reported, so a broken list is reported once rather than in every
# session. A list leaves it when it works again; forget() clears it all
REPORTED_KEY = "GeoFA/code_list_problems"
NULL_VALUE = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"  # how QGIS's ValueMap stores "no value"
NO_VALUE = "<ingen værdi>"
TIMEOUT_MS = 20000
# Widgets the plugin sets on coded fields; any other widget is the user's own (or 0.36's) and is left alone
OWN_WIDGETS = ("ValueMap", "TextEdit", "")


@dataclass(frozen=True)
class Source:
    """Where GeoFA keeps a code list: a table, its code and text columns, and a filter (e.g. aktiv=1)."""
    table: str
    value: str
    text: str
    where: str = ""

    def query(self):
        where = f" WHERE {self.where}" if self.where else ""
        return f"SELECT ({self.value})::text AS v, ({self.text})::text AS t FROM {self.table}{where}"

    def url(self, host):
        return f"{host}{SQL_PATH}?q={urllib.parse.quote(self.query())}"


class CodeListError(Exception):
    """A code list that couldn't be read, or doesn't look like a code list."""


def _first_line(text):
    line = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    return line[:200]


def _code_order(code):
    return (0, int(code), "") if code.lstrip("-").isdigit() else (1, 0, code.lower())


def parse(data):
    """[(code, text), ...] in code order, from GeoFA's SQL API answer. Raises CodeListError."""
    try:
        answer = json.loads(bytes(data).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        raise CodeListError("GeoFA svarede ikke med en kodeliste") from None
    if not isinstance(answer, dict) or not answer.get("success"):
        message = answer.get("message") if isinstance(answer, dict) else None
        raise CodeListError(_first_line(message) or "GeoFA kunne ikke læse kodelisten")
    rows = [feature.get("properties") or {} for feature in answer.get("features") or []]
    values = [(str(row["v"]), str(row["t"] if row.get("t") is not None else row["v"]))
              for row in rows if row.get("v") is not None]
    if not values:
        raise CodeListError("kodelisten er tom")
    if len({code for code, _ in values}) != len(values):
        raise CodeListError("kodelisten har den samme kode flere gange")
    return sorted(values, key=lambda pair: _code_order(pair[0]))


def dropdown(values):
    """The dropdown for a code list: the texts shown, the codes stored.

    Every list starts with "<ingen værdi>", so an empty field reads the same everywhere rather
    than as QGIS's "(NULL)". Fields GeoFA requires are marked by a not-null constraint in the
    style, not here."""
    options = [{NO_VALUE: NULL_VALUE}] + [{text: code} for code, text in values]
    return QgsEditorWidgetSetup("ValueMap", {"map": options})


def codes_only():
    """The field as a plain value: the codes show, and can be typed."""
    return QgsEditorWidgetSetup("TextEdit", {"IsMultiline": False, "UseHtml": False})


def apply(layer, entries, lists):
    """Give the layer's coded fields their dropdowns.

    entries: [(field, Source, required)]; lists: {Source: [(code, text)], or None if it
    couldn't be read}. Fields whose list couldn't be read show the codes.
    """
    fields = layer.fields()
    for field, source, _ in entries:
        index = fields.indexOf(field)
        if index < 0 or source not in lists:
            continue
        current = layer.editorWidgetSetup(index)
        if current.type() not in OWN_WIDGETS:
            continue
        values = lists[source]
        setup = dropdown(values) if values is not None else codes_only()
        if setup.type() == current.type() and setup.config() == current.config():
            continue
        layer.setEditorWidgetSetup(index, setup)


def _present(layer, dataset):
    """The dataset's coded fields that the layer has (a layer may lack a field the spec added later)."""
    try:
        fields = layer.fields()
    except RuntimeError:
        return ()
    return tuple(entry for entry in dataset.code_lists if fields.indexOf(entry[0]) >= 0)


_RUNNING = set()  # Python must keep its tasks alive while QGIS runs them


class FetchTask(QgsTask):
    """Reads one URL in a background thread through QGIS's network stack (its proxy and SSL
    settings); done(data, error) is called on the main thread when it ends.

    It runs off the main thread because a reply handled there while QGIS is creating a WFS
    layer can crash QGIS. Cookies are neither sent nor stored: GeoFA's SQL API starts a PHP
    session (PHPSESSID), which in QGIS's shared cookie jar would also go out with the layers'
    WFS requests. The anonymous code list requests need no session.
    """

    def __init__(self, url, done):
        super().__init__("GeoFA-kodeliste", QgsTask.Flag.CanCancel | QgsTask.Flag.Hidden)
        self.url, self.done = url, done
        self.data, self.error = b"", None
        self.feedback = QgsFeedback()

    def run(self):
        request = QNetworkRequest(QUrl(self.url))
        attribute, control = QNetworkRequest.Attribute, QNetworkRequest.LoadControl
        request.setAttribute(attribute.CookieLoadControlAttribute, control.Manual)
        request.setAttribute(attribute.CookieSaveControlAttribute, control.Manual)
        request.setTransferTimeout(TIMEOUT_MS)
        blocking = QgsBlockingNetworkRequest()
        code = blocking.get(request, True, self.feedback)
        self.data = bytes(blocking.reply().content())
        if code != QgsBlockingNetworkRequest.ErrorCode.NoError:
            self.error = blocking.errorMessage() or "GeoFA svarede ikke"
        return not self.isCanceled()

    def cancel(self):
        self.feedback.cancel()
        super().cancel()

    def finished(self, result):
        _RUNNING.discard(self)
        if self.done:
            self.done(self.data if result else b"", self.error if result else "afbrudt")


def network_fetch(url, done):
    """Read a URL in the background; done(data, error) on the main thread. Returns the task."""
    task = FetchTask(url, done)
    _RUNNING.add(task)
    QgsApplication.taskManager().addTask(task)
    return task


def stop_fetching():
    """Cancel running reads, without calling back (the plugin is being unloaded)."""
    for task in list(_RUNNING):
        task.done = None
        task.cancel()


class CodeLists(QObject):
    """Reads GeoFA's code lists (once per session and environment) and fills layers' dropdowns."""

    # [{"table", "host", "reason", "fields": [...]}], for lists that couldn't be read and weren't reported yet
    problems = pyqtSignal(list)

    def __init__(self, fetch=None, parent=None):
        super().__init__(parent)
        self.fetch = fetch or network_fetch  # fetch(url, done): tests pass a fake GeoFA
        self.lists = {}  # (host, Source) -> [(code, text)], or None when it couldn't be read
        self.reasons = {}  # (host, Source) -> why it couldn't be read
        self.waiting = {}  # (host, Source) -> [batch, ...] while its request is out

    @staticmethod
    def _key_text(key):
        host, source = key
        return "|".join((host, source.table, source.value, source.text, source.where))

    def _reported(self):
        value = QgsSettings().value(REPORTED_KEY, []) or []
        return set([value] if isinstance(value, str) else value)  # QSettings returns a one-item list as a string

    def _set_reported(self, reported):
        QgsSettings().setValue(REPORTED_KEY, sorted(reported))

    def forget(self):
        """Read every list again, and report every problem again (the Opdater action)."""
        self.lists.clear()
        self.reasons.clear()
        self._set_reported(set())

    def fill(self, layers):
        """Fill the dropdowns of [(layer, dataset, host)]: at once from lists already read,
        the rest when GeoFA answers."""
        present = [(layer, _present(layer, dataset), host) for layer, dataset, host in layers]
        keys = {(host, source) for _, entries, host in present for _, source, _ in entries}
        batch = {"layers": present, "pending": {key for key in keys if key not in self.lists}}
        if not batch["pending"]:
            self._finish(batch)
            return
        for key in sorted(batch["pending"], key=lambda k: (k[0], k[1].table, k[1].value)):
            if key in self.waiting:
                self.waiting[key].append(batch)
                continue
            self.waiting[key] = [batch]
            host, source = key
            self.fetch(source.url(host), functools.partial(self._done, key))

    def _done(self, key, data, error):
        try:
            if not data:
                raise CodeListError(_first_line(error) or "GeoFA svarede ikke")
            self.lists[key] = parse(data)
            reported = self._reported()
            if self._key_text(key) in reported:  # it works again: a new failure is reported again
                self._set_reported(reported - {self._key_text(key)})
        except CodeListError as problem:
            self.lists[key] = None
            self.reasons[key] = str(problem)
        for batch in self.waiting.pop(key, []):
            batch["pending"].discard(key)
            if not batch["pending"]:
                self._finish(batch)

    def _finish(self, batch):
        problems = {}
        reported = self._reported()
        for layer, entries, host in batch["layers"]:
            lists = {source: self.lists.get((host, source)) for _, source, _ in entries}
            try:
                apply(layer, entries, lists)
                name = layer.name()
            except RuntimeError:  # the layer was removed while GeoFA answered
                continue
            for field, source, _ in entries:
                key = (host, source)
                if lists.get(source) is None and key in self.reasons and self._key_text(key) not in reported:
                    problem = problems.setdefault(key, {"table": source.table, "host": host,
                                                        "reason": self.reasons[key], "fields": []})
                    problem["fields"].append(f"{name}: {field}")
        if problems:
            self._set_reported(reported | {self._key_text(key) for key in problems})
            self.problems.emit(list(problems.values()))
