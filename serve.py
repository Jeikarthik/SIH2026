"""Start the CNAS console.

    python serve.py            # http://127.0.0.1:8077
    python serve.py --port 9000

Run `python run_pipeline.py` first: the server reads data/graph.json and
data/findings.json, which the pipeline produces.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser

import uvicorn

from cnas import config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8077)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not config.GRAPH_PATH.exists() or not config.FINDINGS_PATH.exists():
        print("No data found. Run:  python run_pipeline.py", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"\n  CNAS console -> {url}\n  Ctrl-C to stop\n")
    if not args.no_open:
        webbrowser.open(url)
    uvicorn.run("cnas.api:app", host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
