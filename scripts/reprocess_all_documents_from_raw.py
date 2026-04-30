#!/usr/bin/env python3
"""Reprocess all FIA documents from stored raw_text in controlled batches."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib import error, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=3600) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-run classification, extraction, and summarization for all stored FIA documents using raw_text."
    )
    parser.add_argument("--base-url", default="http://localhost:8000/fia-documents")
    parser.add_argument("--total-documents", type=int, default=205)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    parser.add_argument("--clear-failed-ai-result", action="store_true", default=True)
    parser.add_argument("--keep-failed-ai-result", action="store_true")
    args = parser.parse_args()

    clear_failed = args.clear_failed_ai_result and not args.keep_failed_ai_result
    url = f"{args.base_url.rstrip('/')}/documents/reprocess-from-raw"

    payload = {
        "max_documents": args.total_documents,
        "batch_size": args.batch_size,
        "pause_seconds": args.pause_seconds,
        "clear_failed_ai_result": clear_failed,
    }

    print(f"Posting to {url}")
    print(json.dumps(payload, indent=2))

    started = time.time()
    try:
        result = post_json(url, payload)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    elapsed = time.time() - started
    print("\nReprocess result:")
    print(json.dumps(result, indent=2))
    print(f"\nElapsed seconds: {elapsed:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
