"""Agent registry management."""

import json

from .constants import SUPPORTED_AGENT_TYPES
from .errors import NotifyError
from .paths import agents_path
from .storage import atomic_write_json, read_json, write_lock, ensure_dirs
from .utils import print_json
from .paths import repo_notify_root


def load_agents(root):
    return [record["name"] for record in load_agent_records(root)]


def normalize_agent_record(entry):
    if isinstance(entry, str):
        agent_type = entry if entry in SUPPORTED_AGENT_TYPES else None
        return {"name": entry, "type": agent_type, "main": False}
    if isinstance(entry, dict):
        name = entry.get("name")
        agent_type = entry.get("type")
        main = entry.get("main", False)
        if isinstance(name, str) and isinstance(agent_type, str) and isinstance(main, bool):
            return {"name": name, "type": agent_type, "main": main}
    raise NotifyError("invalid agents registry")


def require_single_main(records):
    mains = [record for record in records if record["main"]]
    if len(mains) > 1:
        raise NotifyError("invalid agents registry: multiple main-agents")
    return mains[0] if mains else None


def main_agent_name(root):
    main = require_single_main(load_agent_records(root))
    return None if main is None else main["name"]


def is_main_agent(root, agent):
    return main_agent_name(root) == agent

def load_agent_records(root):
    path = agents_path(root)
    if not path.exists():
        return []
    data = read_json(path)
    agents = data.get("agents")
    if not isinstance(agents, list):
        raise NotifyError(f"{path}: invalid agents registry")
    records_by_name = {}
    for entry in agents:
        record = normalize_agent_record(entry)
        if record["type"] is not None and record["type"] not in SUPPORTED_AGENT_TYPES:
            raise NotifyError(f"{path}: unsupported agent type: {record['type']}")
        records_by_name[record["name"]] = record
    records = [records_by_name[name] for name in sorted(records_by_name)]
    require_single_main(records)
    return records

def save_agent_records(root, records):
    records_by_name = {
        record["name"]: {"name": record["name"], "type": record["type"], "main": bool(record["main"])}
        for record in records
    }
    atomic_write_json(
        agents_path(root),
        {"version": 2, "agents": [records_by_name[name] for name in sorted(records_by_name)]},
    )

def require_agent(root, agent):
    if agent not in load_agents(root):
        raise NotifyError(f"unregistered agent: {agent}")

def agent_type(root, agent):
    for record in load_agent_records(root):
        if record["name"] == agent:
            return record["type"]
    raise NotifyError(f"unregistered agent: {agent}")

def infer_agent_type(agent, explicit_type):
    if explicit_type is not None:
        if explicit_type not in SUPPORTED_AGENT_TYPES:
            raise NotifyError(f"unsupported agent type: {explicit_type}")
        return explicit_type
    if agent in SUPPORTED_AGENT_TYPES:
        return agent
    raise NotifyError(f"agent type is required for {agent}; use --type codex, --type claude, or --type reasonix")

def command_register(args):
    root = repo_notify_root()
    with write_lock(root):
        ensure_dirs(root)
        records = load_agent_records(root)
        current_main = require_single_main(records)
        if args.agent in {record["name"] for record in records}:
            raise NotifyError(f"agent already registered: {args.agent}")
        if current_main is None and not args.main:
            raise NotifyError("cannot register non-main agent before a main-agent exists")
        if current_main is not None and args.main:
            raise NotifyError(f"main-agent already exists: {current_main['name']}")
        records.append(
            {"name": args.agent, "type": infer_agent_type(args.agent, args.agent_type), "main": bool(args.main)}
        )
        save_agent_records(root, records)
    print_json(load_agents(root))


def command_set_main(args):
    root = repo_notify_root()
    with write_lock(root):
        ensure_dirs(root)
        records = load_agent_records(root)
        target = None
        for record in records:
            if record["name"] == args.agent:
                target = record
                break
        if target is None:
            raise NotifyError(f"unregistered agent: {args.agent}")
        if target["main"]:
            raise NotifyError(f"agent is already the main-agent: {args.agent}")
        for record in records:
            record["main"] = record["name"] == args.agent
        save_agent_records(root, records)
    print_json({"main_agent": args.agent, "updated": True})


def command_agents(args):
    root = repo_notify_root()
    ensure_dirs(root)
    if args.details:
        print_json(load_agent_records(root))
    else:
        print_json(load_agents(root))
