"""Pipeline 05d — Resume polling a Together fine-tune job and capture the model.

Pipelines/05c_finetune_together.py submits the job and polls in-process. If
the host process dies (e.g., 10-minute subprocess timeout) before the job
reaches a terminal state, this script reads the meta JSON written at submit
time, re-polls Together's API until the job is terminal, and updates the meta
file with the fine-tuned model name.

Usage:
    python pipelines/05d_finetune_together_harvest.py

Idempotent: safe to run repeatedly. If meta already has fine_tuned_model and
status=completed, exits immediately.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
META_PATH    = DATA_PROC / "finetune_together_meta.json"

sys.path.insert(0, str(PROJECT_ROOT))


def _get_together_key() -> str:
    key = os.environ.get("TOGETHER_API_KEY", "").strip()
    if key:
        return key
    for candidate in (PROJECT_ROOT / "TogetherKey.txt",
                      PROJECT_ROOT.parent / "TogetherKey.txt"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    raise RuntimeError("Together API key not found.")


def main() -> None:
    if not META_PATH.exists():
        raise SystemExit(
            f"No meta file at {META_PATH}. Run pipelines/05c_finetune_together.py first."
        )
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))

    if meta.get("status") == "completed" and meta.get("fine_tuned_model"):
        print(f"Already completed. Fine-tuned model: {meta['fine_tuned_model']}")
        return

    job_id = meta.get("job_id")
    if not job_id:
        raise SystemExit("Meta file missing job_id.")

    print(f"Resuming poll for Together fine-tune job {job_id}")
    from together import Together
    client = Together(api_key=_get_together_key())

    submitted_at = meta.get("submitted_at", int(time.time()))
    while True:
        j = client.fine_tuning.retrieve(job_id)
        elapsed = (time.time() - submitted_at) / 60
        print(f"  [{elapsed:5.1f} min] status={j.status}")
        if j.status in {"completed", "error", "cancelled", "failed"}:
            break
        time.sleep(30)

    if j.status != "completed":
        print(f"\nJob ended in non-success state: {j.status}")
        if hasattr(j, "events") and j.events:
            for e in (j.events or [])[-5:]:
                print(f"  {e}")
        raise SystemExit(1)

    fine_tuned_model = (
        getattr(j, "model_output_name", None)
        or getattr(j, "x_model_output_name", None)
        or getattr(j, "output_name", None)
        or getattr(j, "fine_tuned_model", None)
    )
    if not fine_tuned_model:
        print(f"\nWARN: could not auto-detect model name; full job: {j}")
        raise SystemExit(1)

    print(f"\n=== Fine-tune complete ===")
    print(f"  fine-tuned model: {fine_tuned_model}")

    meta["fine_tuned_model"] = fine_tuned_model
    meta["completed_at"]     = int(time.time())
    meta["status"]           = "completed"
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  meta updated   : {META_PATH}")


if __name__ == "__main__":
    main()
