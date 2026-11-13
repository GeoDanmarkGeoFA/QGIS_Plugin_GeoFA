# -*- coding: utf-8 -*-
"""GeoFA login kept in QGIS's encrypted password store (the auth database).

Layers point at the login by id (``authcfg=geofa01``), so the password never ends up
in the QGIS settings file or in saved projects. A colleague who opens a shared
project uses their own stored GeoFA login, not the sender's.
"""
from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsDataSourceUri
from qgis.PyQt.QtCore import QSettings

AUTHCFG_ID = "geofa01"  # QGIS auth ids are exactly 7 characters
AUTHCFG_NAME = "GeoFA"
# Where versions before the password store kept the password in plain text
LEGACY_PASSWORD_KEY = "plugins/GeoFA/password"


def _manager():
    return QgsApplication.authManager()


def auth_username(username):
    """GeoFA (GC2) users log in as <user>@fkg."""
    return f"{username}@fkg"


def has_login():
    """True when a GeoFA login is in the password store (no master password needed)."""
    return AUTHCFG_ID in _manager().configIds()


def legacy_password():
    return QSettings().value(LEGACY_PASSWORD_KEY, "") or ""


def has_password():
    """A password is available, either stored or still waiting to be moved from old settings."""
    return has_login() or bool(legacy_password())


def save_login(username, password=None):
    """Store the GeoFA login. With ``password=None`` the existing password is kept.

    May show QGIS's master password prompt. Returns True when the login is stored.
    """
    if not username:
        return False
    manager = _manager()
    if not manager.setMasterPassword(True):
        return False

    config = QgsAuthMethodConfig()
    exists = has_login()
    if exists:
        loaded, config = manager.loadAuthenticationConfig(AUTHCFG_ID, config, True)
        exists = bool(loaded)
        if not exists:
            config = QgsAuthMethodConfig()
    if password is None:
        password = config.config("password") if exists else legacy_password()
    if not password:
        return False

    config.setId(AUTHCFG_ID)
    config.setName(AUTHCFG_NAME)
    config.setMethod("Basic")
    config.setConfig("username", auth_username(username))
    config.setConfig("password", password)
    if exists:
        stored = manager.updateAuthenticationConfig(config)
    else:
        result = manager.storeAuthenticationConfig(config)
        stored = result[0] if isinstance(result, tuple) else result
    if stored:
        QSettings().remove(LEGACY_PASSWORD_KEY)
    return bool(stored)


def remove_login():
    """Forget the GeoFA login, including any old plain-text password."""
    if has_login():
        _manager().removeAuthenticationConfig(AUTHCFG_ID)
    QSettings().remove(LEGACY_PASSWORD_KEY)


def ensure_login(username):
    """Make sure a login is stored, moving an old plain-text password in if there is one."""
    if has_login():
        return True
    if username and legacy_password():
        return save_login(username)
    return False


def uses_login(source):
    """True when a layer source gets its login from the password store (``authcfg=geofa01``)."""
    return QgsDataSourceUri(source).authConfigId() == AUTHCFG_ID


def secure_layer_source(source):
    """Swap a plain user/password in a layer source for the stored login.

    Returns the new source, or None when the source holds no password.
    """
    uri = QgsDataSourceUri(source)
    if not uri.password():
        return None
    uri.setUsername("")
    uri.setPassword("")
    uri.setAuthConfigId(AUTHCFG_ID)
    return uri.uri(False)
