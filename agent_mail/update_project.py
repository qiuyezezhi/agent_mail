"""Project-local update command."""

from .errors import NotifyError
from .init_project import allow_direnv, ensure_gitignore_entry, ensure_project_entrypoint, ensure_project_envrc
from .paths import repo_notify_root
from .storage import ensure_dirs
from .utils import print_json
from .watch_service import install_watcher, uninstall_watcher, watcher_status


def command_update(args):
    root = repo_notify_root()
    project_root = root.parent
    ensure_dirs(root)
    gitignore_updated = False if args.no_gitignore else ensure_gitignore_entry(project_root)
    envrc_updated = ensure_project_envrc(project_root)
    entrypoint_updated = ensure_project_entrypoint(project_root, force=True)
    direnv_status = {"available": False, "allowed": False, "reason": "skipped"}
    if not args.no_direnv:
        direnv_status = allow_direnv(project_root)

    watcher = update_watcher(root, args)
    print_json(
        {
            "root": str(root.resolve()),
            "gitignore_updated": gitignore_updated,
            "envrc_updated": envrc_updated,
            "entrypoint_updated": entrypoint_updated,
            "direnv": direnv_status,
            "watcher": watcher,
        }
    )


def update_watcher(root, args):
    if args.no_watch:
        return {"checked": False, "updated": False, "reason": "skipped"}
    try:
        status = watcher_status(root)
    except NotifyError as exc:
        return {"checked": False, "updated": False, "reason": str(exc)}
    if not status.get("installed"):
        return {"checked": True, "updated": False, "reason": "watcher not installed", "before": status}

    agents = args.watch_agents if args.watch_agents is not None else status.get("agents", "")
    interval = args.interval if args.interval is not None else status.get("interval", 5)
    timeout = args.timeout if args.timeout is not None else status.get("timeout", 1800)
    removed = uninstall_watcher(root)
    installed = install_watcher(root, agents, interval, timeout)
    return {
        "checked": True,
        "updated": True,
        "before": status,
        "uninstalled": removed,
        "installed": installed,
        "agents": agents,
        "interval": interval,
        "timeout": timeout,
    }
