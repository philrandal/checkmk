#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

import abc
import os
from typing import List, Optional, Dict, Any, Tuple

from livestatus import SiteId

import cmk.utils.store as store
import cmk.utils.plugin_registry

from cmk.gui.globals import g
from cmk.gui.i18n import _
import cmk.gui.config as config
from cmk.utils.type_defs import UserId

UserSpec = Dict[str, Any]  # TODO: Improve this type
RoleSpec = Dict[str, Any]  # TODO: Improve this type
Roles = Dict[str, RoleSpec]  # TODO: Improve this type
UserConnectionSpec = Dict[str, Any]  # TODO: Improve this type
UserSyncConfig = Optional[str]


def load_cached_profile(user_id):
    # type: (UserId) -> Optional[UserSpec]
    user = config.LoggedInUser(user_id) if user_id != config.user.id else config.user
    return user.load_file("cached_profile", None)


def _multisite_dir():
    # type: () -> str
    return cmk.utils.paths.default_config_dir + "/multisite.d/wato/"


def _root_dir():
    # type: () -> str
    return cmk.utils.paths.check_mk_config_dir + "/wato/"


def release_users_lock():
    # type: () -> None
    store.release_lock(_root_dir() + "contacts.mk")


def user_sync_config():
    # type: () -> UserSyncConfig
    # use global option as default for reading legacy options and on remote site
    # for reading the value set by the WATO master site
    default_cfg = user_sync_default_config(config.omd_site())
    return config.site(config.omd_site()).get("user_sync", default_cfg)


# Legacy option config.userdb_automatic_sync defaulted to "master".
# Can be: None: (no sync), "all": all sites sync, "master": only master site sync
# Take that option into account for compatibility reasons.
# For remote sites in distributed setups, the default is to do no sync.
def user_sync_default_config(site_name):
    # type: (SiteId) -> UserSyncConfig
    global_user_sync = _transform_userdb_automatic_sync(config.userdb_automatic_sync)
    if global_user_sync == "master":
        if config.site_is_local(site_name) and not config.is_wato_slave_site():
            user_sync_default = "all"  # type: UserSyncConfig
        else:
            user_sync_default = None
    else:
        user_sync_default = global_user_sync

    return user_sync_default


# Old vs:
#ListChoice(
#    title = _('Automatic User Synchronization'),
#    help  = _('By default the users are synchronized automatically in several situations. '
#              'The sync is started when opening the "Users" page in configuration and '
#              'during each page rendering. Each connector can then specify if it wants to perform '
#              'any actions. For example the LDAP connector will start the sync once the cached user '
#              'information are too old.'),
#    default_value = [ 'wato_users', 'page', 'wato_pre_activate_changes', 'wato_snapshot_pushed' ],
#    choices       = [
#        ('page',                      _('During regular page processing')),
#        ('wato_users',                _('When opening the users\' configuration page')),
#        ('wato_pre_activate_changes', _('Before activating the changed configuration')),
#        ('wato_snapshot_pushed',      _('On a remote site, when it receives a new configuration')),
#    ],
#    allow_empty   = True,
#),
def _transform_userdb_automatic_sync(val):
    if val == []:
        # legacy compat - disabled
        return None

    if isinstance(val, list) and val:
        # legacy compat - all connections
        return "all"

    return val


def new_user_template(connection_id):
    # type: (str) -> UserSpec
    new_user = {
        'serial': 0,
        'connector': connection_id,
    }

    # Apply the default user profile
    new_user.update(config.default_user_profile)
    return new_user


#   .--Connections---------------------------------------------------------.
#   |        ____                            _   _                         |
#   |       / ___|___  _ __  _ __   ___  ___| |_(_) ___  _ __  ___         |
#   |      | |   / _ \| '_ \| '_ \ / _ \/ __| __| |/ _ \| '_ \/ __|        |
#   |      | |__| (_) | | | | | | |  __/ (__| |_| | (_) | | | \__ \        |
#   |       \____\___/|_| |_|_| |_|\___|\___|\__|_|\___/|_| |_|___/        |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Managing the configured connections                                  |
#   '----------------------------------------------------------------------'


def cleanup_connection_id(connection_id):
    # type: (Optional[str]) -> str
    if connection_id is None:
        return 'htpasswd'

    # Old Check_MK used a static "ldap" connector id for all LDAP users.
    # Since Check_MK now supports multiple LDAP connections, the ID has
    # been changed to "default". But only transform this when there is
    # no connection existing with the id LDAP.
    if connection_id == 'ldap' and not get_connection('ldap'):
        return 'default'

    return connection_id


def get_connection(connection_id):
    # type: (Optional[str]) -> Optional[UserConnector]
    """Returns the connection object of the requested connection id

    This function maintains a cache that for a single connection_id only one object per request is
    created."""
    if 'user_connections' not in g:
        g.user_connections = {}

    if connection_id not in g.user_connections:
        connections_with_id = [c for cid, c in _all_connections() if cid == connection_id]
        # NOTE: We cache even failed lookups.
        g.user_connections[connection_id] = connections_with_id[0] if connections_with_id else None

    return g.user_connections[connection_id]


def active_connections():
    # type: () -> List[Tuple[str, UserConnector]]
    enabled_configs = [
        cfg  #
        for cfg in _get_connection_configs()
        if not cfg['disabled']
    ]
    return [
        (connection_id, connection)  #
        for connection_id, connection in _get_connections_for(enabled_configs)
        if connection.is_enabled()
    ]


def connection_choices():
    # type: () -> List[Tuple[str, str]]
    return sorted([(connection_id, "%s (%s)" % (connection_id, connection.type()))
                   for connection_id, connection in _all_connections()
                   if connection.type() == "ldap"],
                  key=lambda id_and_description: id_and_description[1])


def _all_connections():
    # type: () -> List[Tuple[str, UserConnector]]
    return _get_connections_for(_get_connection_configs())


def _get_connections_for(configs):
    # type: (List[Dict[str, Any]]) -> List[Tuple[str, UserConnector]]
    return [(cfg['id'], user_connector_registry[cfg['type']](cfg)) for cfg in configs]


def _get_connection_configs():
    # type: () -> List[Dict[str, Any]]
    # The htpasswd connector is enabled by default and always executed first.
    return [_HTPASSWD_CONNECTION] + config.user_connections


_HTPASSWD_CONNECTION = {
    'type': 'htpasswd',
    'id': 'htpasswd',
    'disabled': False,
}

#.
#   .--ConnectorCfg--------------------------------------------------------.
#   |    ____                            _              ____  __           |
#   |   / ___|___  _ __  _ __   ___  ___| |_ ___  _ __ / ___|/ _| __ _     |
#   |  | |   / _ \| '_ \| '_ \ / _ \/ __| __/ _ \| '__| |   | |_ / _` |    |
#   |  | |__| (_) | | | | | | |  __/ (__| || (_) | |  | |___|  _| (_| |    |
#   |   \____\___/|_| |_|_| |_|\___|\___|\__\___/|_|   \____|_|  \__, |    |
#   |                                                            |___/     |
#   +----------------------------------------------------------------------+
#   | The user can enable and configure a list of user connectors which    |
#   | are then used by the userdb to fetch user / group information from   |
#   | external sources like LDAP servers.                                  |
#   '----------------------------------------------------------------------'


def load_connection_config(lock=False):
    # type: (bool) -> List[UserConnectionSpec]
    filename = os.path.join(_multisite_dir(), "user_connections.mk")
    return store.load_from_mk_file(filename, "user_connections", default=[], lock=lock)


def save_connection_config(connections, base_dir=None):
    # type: (List[UserConnectionSpec], str) -> None
    if not base_dir:
        base_dir = _multisite_dir()
    store.mkdir(base_dir)
    store.save_to_mk_file(os.path.join(base_dir, "user_connections.mk"), "user_connections",
                          connections)

    for connector_class in user_connector_registry.values():
        connector_class.config_changed()


#.
#   .-Roles----------------------------------------------------------------.
#   |                       ____       _                                   |
#   |                      |  _ \ ___ | | ___  ___                         |
#   |                      | |_) / _ \| |/ _ \/ __|                        |
#   |                      |  _ < (_) | |  __/\__ \                        |
#   |                      |_| \_\___/|_|\___||___/                        |
#   |                                                                      |
#   +----------------------------------------------------------------------+


def load_roles():
    # type: () -> Roles
    roles = store.load_from_mk_file(
        os.path.join(_multisite_dir(), "roles.mk"),
        "roles",
        default=_get_builtin_roles(),
    )

    # Make sure that "general." is prefixed to the general permissions
    # (due to a code change that converted "use" into "general.use", etc.
    # TODO: Can't we drop this? This seems to be from very early days of the GUI
    for role in roles.values():
        for pname, pvalue in role["permissions"].items():
            if "." not in pname:
                del role["permissions"][pname]
                role["permissions"]["general." + pname] = pvalue

    # Reflect the data in the roles dict kept in the config module needed
    # for instant changes in current page while saving modified roles.
    # Otherwise the hooks would work with old data when using helper
    # functions from the config module
    # TODO: load_roles() should not update global structures
    config.roles.update(roles)

    return roles


def _get_builtin_roles():
    # type: () -> Roles
    """Returns a role dictionary containing the bultin default roles"""
    builtin_role_names = {
        "admin": _("Administrator"),
        "user": _("Normal monitoring user"),
        "guest": _("Guest user"),
    }
    return {
        rid: {
            "alias": builtin_role_names.get(rid, rid),
            "permissions": {},  # use default everywhere
            "builtin": True,
        } for rid in config.builtin_role_ids
    }


#.
#   .--ConnectorAPI--------------------------------------------------------.
#   |     ____                            _              _    ____ ___     |
#   |    / ___|___  _ __  _ __   ___  ___| |_ ___  _ __ / \  |  _ \_ _|    |
#   |   | |   / _ \| '_ \| '_ \ / _ \/ __| __/ _ \| '__/ _ \ | |_) | |     |
#   |   | |__| (_) | | | | | | |  __/ (__| || (_) | | / ___ \|  __/| |     |
#   |    \____\___/|_| |_|_| |_|\___|\___|\__\___/|_|/_/   \_\_|  |___|    |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Implements the base class for User Connector classes. It implements  |
#   | basic mechanisms and default methods which might/should be           |
#   | overridden by the specific connector classes.                        |
#   '----------------------------------------------------------------------'


class UserConnector(metaclass=abc.ABCMeta):
    def __init__(self, cfg):
        super(UserConnector, self).__init__()
        self._config = cfg

    @classmethod
    @abc.abstractmethod
    def type(cls):
        raise NotImplementedError()

    @classmethod
    @abc.abstractmethod
    def title(cls):
        """The string representing this connector to humans"""
        raise NotImplementedError()

    @classmethod
    @abc.abstractmethod
    def short_title(cls):
        raise NotImplementedError()

    @classmethod
    def config_changed(cls):
        return

    #
    # USERDB API METHODS
    #

    @classmethod
    def migrate_config(cls):
        pass

    @abc.abstractmethod
    def is_enabled(self):
        raise NotImplementedError()

    # Optional: Hook function can be registered here to be executed
    # to validate a login issued by a user.
    # Gets parameters: username, password
    # Has to return either:
    #     '<user_id>' -> Login succeeded
    #     False       -> Login failed
    #     None        -> Unknown user
    @abc.abstractmethod
    def check_credentials(self, user_id, password):
        return None

    # Optional: Hook function can be registered here to be executed
    # to synchronize all users.
    def do_sync(self, add_to_changelog, only_username, load_users_func, save_users_func):
        pass

    # Optional: Tells whether or not the synchronization (using do_sync()
    # method) is needed.
    def sync_is_needed(self):
        return False

    # Optional: Hook function can be registered here to be xecuted
    # to save all users.
    def save_users(self, users):
        pass

    # List of user attributes locked for all users attached to this
    # connection. Those locked attributes are read-only in WATO.
    def locked_attributes(self):
        # type: () -> List[str]
        return []

    def multisite_attributes(self):
        # type: () -> List[str]
        return []

    def non_contact_attributes(self):
        # type: () -> List[str]
        return []


#.
#   .--UserAttribute-------------------------------------------------------.
#   |     _   _                _   _   _        _ _           _            |
#   |    | | | |___  ___ _ __ / \ | |_| |_ _ __(_) |__  _   _| |_ ___      |
#   |    | | | / __|/ _ \ '__/ _ \| __| __| '__| | '_ \| | | | __/ _ \     |
#   |    | |_| \__ \  __/ | / ___ \ |_| |_| |  | | |_) | |_| | ||  __/     |
#   |     \___/|___/\___|_|/_/   \_\__|\__|_|  |_|_.__/ \__,_|\__\___|     |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Base class for user attributes                                       |
#   '----------------------------------------------------------------------'


class UserAttribute(metaclass=abc.ABCMeta):
    @classmethod
    @abc.abstractmethod
    def name(cls):
        # type: () -> str
        raise NotImplementedError()

    @abc.abstractmethod
    def topic(self):
        # type: () -> str
        raise NotImplementedError()

    @abc.abstractmethod
    def valuespec(self):
        raise NotImplementedError()

    def from_config(self):
        # type: () -> bool
        return False

    def user_editable(self):
        # type: () -> bool
        return True

    def permission(self):
        # type: () -> Optional[str]
        return None

    def show_in_table(self):
        # type: () -> bool
        return False

    def add_custom_macro(self):
        # type: () -> bool
        return False

    def domain(self):
        # type: () -> str
        return "multisite"


#.
#   .--Plugins-------------------------------------------------------------.
#   |                   ____  _             _                              |
#   |                  |  _ \| |_   _  __ _(_)_ __  ___                    |
#   |                  | |_) | | | | |/ _` | | '_ \/ __|                   |
#   |                  |  __/| | |_| | (_| | | | | \__ \                   |
#   |                  |_|   |_|\__,_|\__, |_|_| |_|___/                   |
#   |                                 |___/                                |
#   '----------------------------------------------------------------------'


class UserConnectorRegistry(cmk.utils.plugin_registry.ClassRegistry):
    """The management object for all available user connector classes.

    Have a look at the base class for details."""
    def plugin_base_class(self):
        return UserConnector

    def plugin_name(self, plugin_class):
        return plugin_class.type()

    def registration_hook(self, plugin_class):
        plugin_class.migrate_config()


user_connector_registry = UserConnectorRegistry()


class UserAttributeRegistry(cmk.utils.plugin_registry.ClassRegistry):
    """The management object for all available user attributes.
    Have a look at the base class for details."""
    def plugin_base_class(self):
        return UserAttribute

    def plugin_name(self, plugin_class):
        return plugin_class.name()


user_attribute_registry = UserAttributeRegistry()


def get_user_attributes():
    return [(name, attribute_class()) for name, attribute_class in user_attribute_registry.items()]