"""Print local attention summaries from host-exported JSONL on stdin.

Usage: Get-Content <export.jsonl> | python notify_updates.py
No external messages are sent. Unchanged records are silent.
"""
import json
import sys


def summarize(record):
    data = record.get("data") or {}
    if not data.get("attention"):
        return ""
    return " · ".join(str(data.get(key) or "") for key in ("signal", "subject", "title", "conclusion", "url"))


if __name__ == "__main__":
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = summarize(json.loads(line))
        except (ValueError, AttributeError, TypeError):
            print("跳过无效 JSONL 记录", file=sys.stderr)
            continue
        if message:
            print(message)
