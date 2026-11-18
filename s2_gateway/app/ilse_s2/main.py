"""Add-on entry point: read options, optionally start the self-test CEM, run the gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import threading
import time

from . import __version__
from . import web
from .gateway import Gateway

log = logging.getLogger("ilse_s2")
LOG_PATH = "/data/s2_events.jsonl"
MAX_LOG = 5_000_000


def record(rec: dict) -> None:
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        pass


def start_self_test_cem(port: int, every_min: int) -> None:
    from . import testcem

    def run():
        asyncio.run(testcem.run(port, True, [], every_min=every_min))

    threading.Thread(target=run, daemon=True, name="test-cem").start()
    time.sleep(1.0)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    ap = argparse.ArgumentParser(prog="ilse-s2-gateway")
    ap.add_argument("--options", default="/data/options.json")
    ap.add_argument("--site", default=os.environ.get("ILSE_SITE") or socket.gethostname())
    a = ap.parse_args()
    with open(a.options) as f:
        conf = json.load(f)
    a.site = conf.get("site_name") or a.site
    log.info("ILSE S2 Gateway %s, site %s, %d device(s), shadow mode (read-only)",
             __version__, a.site, len(conf.get("devices") or []))
    if conf.get("self_test_cem", False):
        url = conf.get("cem_url", "")
        port = int(url.split(":")[2].split("/")[0]) if url.count(":") >= 2 else 8003
        start_self_test_cem(port, int(conf.get("self_test_every_min") or 0))
    gw = Gateway(conf, a.site, record=record)
    gw.start()
    web.serve(gw, 8099)
    while True:
        time.sleep(300)
        log.info("health %s", json.dumps(gw.health(), default=str))


if __name__ == "__main__":
    main()
