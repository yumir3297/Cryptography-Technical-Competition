"""Entry point: ``python -m competition.agent`` (the agent-facing gateway).

Environment:
    ZJJ_ENTRY            trusted entry base URL (default http://127.0.0.1:8000)
    ZJJ_ENDPOINTS        endpoint base URL used for read signatures
    ZJJ_CALLERS          callers.jsonl path or its directory
    ZJJ_AGENT_KEYS       this process's own key directory
    ZJJ_AGENT_DB         SQLite journal path
    ZJJ_AGENT_TOKEN      bearer token dsh uses for /mcp and /zjj/*
    ZJJ_INTERNAL_TOKEN   bearer token operator/executor use for /internal/*
    ZJJ_STATUS_POLL_MS   status poll interval (default 1000)
    ZJJ_STATUS_GRACE     seconds before an unreadable submitted op is UNAVAILABLE
"""
import os
import time
from pathlib import Path

from competition.agent.app import serve
from competition.agent.identity import enroll
from competition.agent.journal import Journal
from competition.agent.service import GatewayService


def main():
    entry = os.environ.get('ZJJ_ENTRY', 'http://127.0.0.1:8000')
    endpoints = os.environ.get('ZJJ_ENDPOINTS', 'http://127.0.0.1')
    callers = os.environ.get('ZJJ_CALLERS', '/callers')
    keys = Path(os.environ.get('ZJJ_AGENT_KEYS', '/agent'))
    database = Path(os.environ.get('ZJJ_AGENT_DB', str(keys / 'agent.sqlite')))
    name = os.environ.get('ZJJ_AGENT_NAME', 'zjj-agent')
    host = os.environ.get('ZJJ_AGENT_HOST', '0.0.0.0')
    port = int(os.environ.get('ZJJ_AGENT_PORT', '8090'))
    interval = float(os.environ.get('ZJJ_STATUS_POLL_MS', '1000')) / 1000.0
    grace = float(os.environ.get('ZJJ_STATUS_GRACE', '300'))
    agent_token = os.environ.get('ZJJ_AGENT_TOKEN', '')
    internal_token = os.environ.get('ZJJ_INTERNAL_TOKEN', '')
    if not agent_token or not internal_token:
        raise SystemExit('ZJJ_AGENT_TOKEN and ZJJ_INTERNAL_TOKEN are required')

    key_path, _line = enroll(keys, name, ['H'], callers)
    journal = Journal(database, grace=grace, now=time.time)
    service = GatewayService(entry, key_path, endpoints, journal, now=time.time)
    service.start()
    print('agent gateway on %s:%d; caller %s; db %s'
          % (host, port, name, database), flush=True)
    try:
        serve(service, host, port, agent_token=agent_token,
              internal_token=internal_token, poll_interval=interval)
    finally:
        service.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
