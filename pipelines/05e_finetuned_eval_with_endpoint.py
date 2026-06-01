"""Pipeline 05e — Run the held-out MAE eval against the Together fine-tune.

Together moved custom fine-tunes off the serverless tier on this account, so
the only way to call our fine-tuned model is through a dedicated endpoint.
This script handles the full lifecycle so the endpoint can't outlive the eval:

  1. Create a 2x H100 endpoint for the Qwen2.5-7B fine-tune
     (smallest hardware Together exposes for this model size).
  2. Poll endpoint status until STARTED (typical wait: 1-3 minutes).
  3. Run ``eval/contract_mae.py --use-finetuned`` as a subprocess so its
     output streams directly to the console.
  4. ALWAYS delete the endpoint in the finally block — even if the eval
     crashes — so we don't accrue idle GPU charges.

Cost expectation at $0.2163/min on 2x H100:
  spin-up      ~2 min  → $0.43
  eval (n=26)  ~5 min  → $1.08
  teardown     ~0 min  → $0.00
  Total                ≈ $1.50
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
META_PATH    = DATA_PROC / "finetune_together_meta.json"

sys.path.insert(0, str(PROJECT_ROOT))

HARDWARE        = "2x_nvidia_h100_80gb_sxm"   # cheapest option for 7B fine-tunes
INACTIVE_MIN    = 5                            # auto-shut if idle this long
POLL_INTERVAL_S = 15
MAX_WAIT_MIN    = 10                           # safety: never wait past this


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
        raise SystemExit(f"Run pipelines/05c_finetune_together.py first; no meta at {META_PATH}")
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    ft_model = meta.get("fine_tuned_model")
    if not ft_model or meta.get("status") != "completed":
        raise SystemExit("Fine-tune meta JSON does not have status=completed + fine_tuned_model set.")

    from together import Together
    client = Together(api_key=_get_together_key())

    print(f"=== Pipeline 05e: dedicated-endpoint MAE eval ===")
    print(f"  model     : {ft_model}")
    print(f"  hardware  : {HARDWARE}")
    print(f"  inactive timeout : {INACTIVE_MIN} min (auto-shut safety net)")

    # ── Stage 1: Create endpoint ─────────────────────────────────────────────
    print(f"\nCreating endpoint ...")
    ep = client.endpoints.create(
        model=ft_model,
        hardware=HARDWARE,
        autoscaling={"min_replicas": 1, "max_replicas": 1},
        inactive_timeout=INACTIVE_MIN,
        display_name="sabercast-contract-eval",
    )
    endpoint_id = ep.id
    print(f"  endpoint id: {endpoint_id}")
    print(f"  status     : {ep.state}")
    started_at = time.time()

    try:
        # ── Stage 2: Wait for endpoint to be ready ──────────────────────────
        print(f"\nWaiting for endpoint to reach STARTED ...")
        ep_full = None
        while True:
            ep_full = client.endpoints.retrieve(endpoint_id)
            elapsed = (time.time() - started_at) / 60
            print(f"  [{elapsed:4.1f} min] state={ep_full.state}")
            if ep_full.state == "STARTED":
                break
            if ep_full.state in {"ERROR", "FAILED", "STOPPED"}:
                raise RuntimeError(f"Endpoint reached terminal non-ready state: {ep_full.state}")
            if elapsed > MAX_WAIT_MIN:
                raise RuntimeError(f"Endpoint did not start within {MAX_WAIT_MIN} min")
            time.sleep(POLL_INTERVAL_S)
        print(f"\nEndpoint ready after {elapsed:.1f} min.")

        # ── Stage 2.5: Capture endpoint.name for chat.completions routing ──
        # Per Together docs (BUILD_LOG Entry 15 finding): dedicated endpoints
        # are routed by endpoint.name, NOT the raw model_output_name. Writing
        # it into meta JSON makes _get_finetuned_together_model() in the
        # orchestrator pick it up for the eval subprocess. We restore the
        # meta JSON in the finally block so the published artifact reflects
        # the trained model only (the endpoint name is transient).
        endpoint_name = getattr(ep_full, "name", None)
        if not endpoint_name:
            raise RuntimeError(
                f"Endpoint {endpoint_id} has no .name attribute — cannot route inference. "
                f"Full endpoint: {ep_full}"
            )
        print(f"\nEndpoint name (routing key): {endpoint_name}")
        meta["endpoint_name"] = endpoint_name
        META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"Meta updated with endpoint_name; orchestrator will route to it.")

        # ── Stage 3: Run the MAE eval as a subprocess ───────────────────────
        print(f"\nRunning eval/contract_mae.py --use-finetuned ...\n")
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "eval" / "contract_mae.py"),
             "--use-finetuned"],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        if result.returncode != 0:
            print(f"\nWARN: eval exited with code {result.returncode}")

    finally:
        # ── Stage 4: ALWAYS tear down endpoint + clear transient meta ──────
        elapsed = (time.time() - started_at) / 60
        print(f"\nTearing down endpoint {endpoint_id} (was up {elapsed:.1f} min) ...")
        try:
            client.endpoints.delete(endpoint_id)
            print(f"  endpoint deleted")
        except Exception as e:                                          # noqa: BLE001
            print(f"  WARN: delete failed: {type(e).__name__}: {e}")
            print(f"  Visit https://api.together.ai/endpoints to delete manually.")

        # Strip the transient endpoint_name from meta JSON so the artifact is
        # reproducible — anyone re-running 05e gets a fresh endpoint name.
        try:
            cur_meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            if "endpoint_name" in cur_meta:
                del cur_meta["endpoint_name"]
                META_PATH.write_text(json.dumps(cur_meta, indent=2), encoding="utf-8")
                print(f"  cleared endpoint_name from meta JSON")
        except Exception as e:                                          # noqa: BLE001
            print(f"  WARN: meta cleanup failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
