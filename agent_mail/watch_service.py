"""Platform dispatch for watcher background service management."""

import sys

from .errors import NotifyError
from .paths import repo_notify_root
from .utils import print_json


def _backend():
    if sys.platform == "darwin":
        from . import launchd

        return launchd
    if sys.platform == "win32":
        from . import windows

        return windows
    raise NotifyError("watch install/status/uninstall are only supported on macOS and Windows")


def install_watcher(root, agents, interval, timeout):
    return _backend().install_watcher(root, agents, interval, timeout)


def watcher_status(root):
    return _backend().watcher_status(root)


def uninstall_watcher(root):
    return _backend().uninstall_watcher(root)


def command_watch_install(args):
    root = repo_notify_root()
    print_json(install_watcher(root, args.agents, args.interval, args.timeout))


def command_watch_status(_args):
    root = repo_notify_root()
    print_json(watcher_status(root))


def command_watch_uninstall(_args):
    root = repo_notify_root()
    print_json(uninstall_watcher(root))
