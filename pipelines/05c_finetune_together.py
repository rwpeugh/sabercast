"""Pipeline 05c — Fine-tune a Llama 3.1 8B model on Together AI.

This replaces the OpenAI self-serve fine-tuning route that was deprecated
mid-build (Entry 14). Together AI hosts open-weight models (Llama, Qwen,
Mistral) and offers OpenAI-compatible fine-tuning + inference.

Workflow:
  1. Re-use the JSONL training file built by pipelines/05a_finetune_submit.py.
     It is already in OpenAI chat format which Together accepts directly.
  2. Upload to Together's file endpoint.
  3. Submit a fine-tuning job against Llama 3.1 8B Instruct.
  4. Poll until completion (~10-60 minutes).
  5. Save the fine-tuned model name so the runtime forecaster can use it.

API key: requires TOGETHER_API_KEY environment variable or
st.secrets["TOGETHER_API_KEY"] on Streamlit Cloud.

Cost expectation: ~$0.01-0.05 training, ~$0.005 for the 26-contract MAE eval.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
DATA_PROC.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))

JSONL_PATH = DATA_PROC / "finetune_train_2019_2024.jsonl"
META_PATH  = DATA_PROC / "finetune_together_meta.json"

# Qwen2.5-7B-Instruct — the Llama-3.1-8B-Instruct-Reference fine-tune we ran
# first ended up flagged "non-serverless" by Together's runtime, so inference
# would have required spinning up a dedicated H100 endpoint at $0.43/min.
# Qwen2.5-7B-Instruct-Turbo is on this account's serverless tier, so we
# re-fine-tune against the Qwen base to keep inference cheap and serverless.
# See BUILD_LOG.md Entry 15 for the full backstory.
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
N_EPOCHS   = 3
SUFFIX     = "sabercast-contract"


def _get_together_key() -> str:
    """Return the Together API key from env or local file. Mirrors the OpenAI
    loader pattern in app/config.py."""
    key = os.environ.get("TOGETHER_API_KEY", "").strip()
    if key:
        return key
    candidate = PROJECT_ROOT / "TogetherKey.txt"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8").strip()
    candidate2 = PROJECT_ROOT.parent / "TogetherKey.txt"
    if candidate2.exists():
        return candidate2.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        "Together API key not found. Set TOGETHER_API_KEY env var or place "
        "the key in TogetherKey.txt in the sabercast/ folder or its parent."
    )


def main() -> None:
    if not JSONL_PATH.exists():
        raise SystemExit(
            f"Training JSONL not found at {JSONL_PATH}. "
            f"Run pipelines/05a_finetune_submit.py first to build it."
        )

    print(f"=== Pipeline 05c: Together AI fine-tune ({BASE_MODEL}) ===")
    print(f"Training file: {JSONL_PATH.name} "
          f"({JSONL_PATH.stat().st_size / 1024:.1f} KB)")
    n_examples = sum(1 for _ in JSONL_PATH.open("r", encoding="utf-8"))
    print(f"Examples     : {n_examples}")

    from together import Together
    client = Together(api_key=_get_together_key())

    # ── Upload training file ────────────────────────────────────────────────
    print(f"\nUploading {JSONL_PATH.name} to Together ...")
    upload = client.files.upload(file=str(JSONL_PATH), check=True)
    print(f"  uploaded file id: {upload.id}")

    # ── Submit fine-tuning job ─────────────────────────────────────────────
    print(f"\nSubmitting fine-tuning job ...")
    job = client.fine_tuning.create(
        training_file=upload.id,
        model=BASE_MODEL,
        n_epochs=N_EPOCHS,
        suffix=SUFFIX,
        learning_rate=1e-5,
    )
    print(f"  job id:  {job.id}")
    print(f"  status:  {job.status}")

    meta = {
        "job_id":         job.id,
        "input_file_id":  upload.id,
        "base_model":     BASE_MODEL,
        "n_epochs":       N_EPOCHS,
        "suffix":         SUFFIX,
        "submitted_at":   int(time.time()),
        "n_examples":     n_examples,
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nMeta written to {META_PATH}")

    # ── Poll for completion ─────────────────────────────────────────────────
    print(f"\nPolling for completion (typical wait: 10-60 minutes) ...")
    while True:
        time.sleep(30)
        j = client.fine_tuning.retrieve(job.id)
        elapsed = (time.time() - meta["submitted_at"]) / 60
        print(f"  [{elapsed:5.1f} min] status={j.status}")
        if j.status in {"completed", "error", "cancelled", "failed"}:
            break

    if j.status != "completed":
        print(f"\nJob ended in non-success state: {j.status}")
        if hasattr(j, "events") and j.events:
            for e in (j.events or [])[-5:]:
                print(f"  {e}")
        raise SystemExit(1)

    # ── Capture the fine-tuned model name ──────────────────────────────────
    # SDK v2.16 stores the deployable model under model_output_name (the
    # x_model_output_name alias mirrors it). Older docs reference output_name /
    # fine_tuned_model so we fall back to those for forward compat.
    fine_tuned_model = (
        getattr(j, "model_output_name", None)
        or getattr(j, "x_model_output_name", None)
        or getattr(j, "output_name", None)
        or getattr(j, "fine_tuned_model", None)
    )
    if not fine_tuned_model:
        # Last-ditch dump so we can read the field manually
        print(f"\nWARN: could not auto-detect model name; full job: {j}")
        raise SystemExit(1)

    print(f"\n=== Fine-tune complete ===")
    print(f"  fine-tuned model: {fine_tuned_model}")

    meta["fine_tuned_model"] = fine_tuned_model
    meta["completed_at"]     = int(time.time())
    meta["status"]           = "completed"
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  meta updated   : {META_PATH}")
    print()
    print(f"Next step: run eval/contract_mae.py --use-finetuned to re-score the")
    print(f"26 held-out contracts against the fine-tuned model.")


if __name__ == "__main__":
    main()
