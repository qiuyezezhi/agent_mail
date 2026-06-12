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
        return {"name": entry, "type": agent_type}
    if isinstance(entry, dict):
        name = entry.get("name")
        agent_type = entry.get("type")
        if isinstance(name, str) and isinstance(agent_type, str):
            return {"name": name, "type": agent_type}
    raise NotifyError("invalid agents registry")

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
    return [records_by_name[name] for name in sorted(records_by_name)]

def save_agent_records(root, records):
    records_by_name = {record["name"]: {"name": record["name"], "type": record["type"]} for record in records}
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
        if args.agent in {record["name"] for record in records}:
            raise NotifyError(f"agent already registered: {args.agent}")
        records.append({"name": args.agent, "type": infer_agent_type(args.agent, args.agent_type)})
        save_agent_records(root, records)
    print_json(load_agents(root))

def command_agents(args):
    root = repo_notify_root()
    ensure_dirs(root)
    if args.details:
        print_json(load_agent_records(root))
    else:
        print_json(load_agents(root))
