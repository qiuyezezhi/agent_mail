"""Small shared helpers."""

import json
import os
import sys


def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))

def log_progress(message):
    print(f"[agent-notify] {message}", file=sys.stderr)

def process_is_alive(pid):
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def parse_agent_names(value):
    return list(dict.fromkeys(agent.strip() for agent in value.split(",") if agent.strip()))
