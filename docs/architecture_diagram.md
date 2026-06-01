# Sabercast Architecture

Every box is labeled with the **specific model or store** doing the work. The
diagram supports the final-report section on Technical Depth (35 % of grade)
by making the LLM/agentic role explicit — which model runs in which step, and
how data flows from raw ingest through embedding, retrieval, and reasoning out
to the three user-facing tabs.

GitHub renders this Mermaid block natively. To export to PNG for the Word
deliverable, screenshot the rendered block or run
`npx -p @mermaid-js/mermaid-cli mmdc -i docs/architecture_diagram.md -o docs/architecture_diagram.png`.

```mermaid
flowchart TB
    %% =====================  EXTERNAL DATA SOURCES  =====================
    subgraph SRC["External data sources"]
        direction LR
        PB["pybaseball<br/>(Baseball Reference fallback<br/>after FanGraphs 403)"]
        SP["Spotrac<br/>HTML scrape"]
        SC["Statcast<br/>Baseball Savant"]
    end

    %% =====================  OFFLINE PIPELINES  =====================
    subgraph PIPE["Offline pipelines"]
        direction TB
        P01["01_ingest_pybaseball.py<br/><b>batting + pitching</b><br/>2019-2025"]
        P01B["01b_pull_standings.py<br/><b>team wins</b><br/>2018 + 2019-2025"]
        P02["02_scrape_spotrac.py<br/>+ 02b manual additions<br/><b>115 contracts</b>"]
        P03["03a/b_archetypes_batch<br/><b>gpt-4o-mini</b><br/>via OpenAI Batch API"]
        P04["04_build_vectorstore.py<br/><b>text-embedding-3-small</b>"]
        P05["05c_finetune_together.py<br/>05e_eval_with_endpoint.py<br/><b>Qwen 2.5 7B Instruct</b><br/>+ LoRA r=64 α=128"]
    end

    %% =====================  STORAGE  =====================
    subgraph STORE["Storage (committed to repo)"]
        direction LR
        CSV[("data/raw/*.csv<br/>batting · pitching · contracts<br/>OAA · sprint · catcher pop<br/>standings · archetypes")]
        VDB[("ChromaDB persistent<br/>player profile embeddings<br/>(filtered by signed_year)")]
        FT[("Together fine-tuned model<br/>(MAE eval artifact only —<br/>not runtime)")]
    end

    PB --> P01
    PB --> P01B
    SP --> P02
    SC --> P01
    P01 --> CSV
    P01B --> CSV
    P02 --> CSV
    P03 --> CSV
    CSV --> P04
    P04 --> VDB
    CSV --> P05
    P05 --> FT

    %% =====================  RUNTIME REASONING  =====================
    subgraph RUNTIME["Runtime reasoning · core/orchestrator.py"]
        direction TB
        DG["diagnose_gaps_llm<br/><b>gpt-4o</b><br/>(narrative quality matters)"]
        SCT["scout_opponent_llm<br/><b>gpt-4o</b>"]
        EC["estimate_contract_llm<br/><b>gpt-4o-mini</b>"]
        TF["forecast_target_contract_llm<br/><b>gpt-4o-mini</b> (live)<br/><b>or fine-tuned Qwen 7B</b> (eval)"]
        RB["build_roster_llm<br/><b>gpt-4o-mini</b>"]
        PM["player_matcher.find_matches<br/>RAG: <b>text-embedding-3-small</b><br/>+ position + budget filter"]
    end

    CSV -. read .-> DG
    CSV -. read .-> SCT
    CSV -. read .-> EC
    CSV -. read .-> TF
    CSV -. read .-> RB
    CSV -. read .-> PM
    VDB -. similarity search .-> PM
    PM -. top-k candidates .-> TF
    DG -. ranked gap positions .-> PM

    %% =====================  EVAL  (offline) =====================
    subgraph EVAL["Offline evaluation"]
        direction LR
        CORR["correlation_study.py<br/>180 team-years<br/>2019-2024 → next-year wins"]
        MAE["contract_mae.py<br/>(--use-finetuned A/B)<br/>26 held-out contracts"]
    end

    CSV --> CORR
    DG --> CORR
    CSV --> MAE
    TF --> MAE
    FT -. routed via endpoint name .-> TF

    %% =====================  USER-FACING TABS  =====================
    subgraph APP["Streamlit app · sabercast-mlb.streamlit.app"]
        direction LR
        T1["Tab 1<br/><b>Roster Builder</b><br/>day-to-day lineup<br/>vs opponent"]
        T2["Tab 2<br/><b>Opponent Scouting</b><br/>narrative · top threats<br/>defensive vulnerabilities"]
        T3["Tab 3<br/><b>Gap Filler</b><br/>positions · targets<br/>contract forecasts"]
    end

    RB --> T1
    SCT --> T2
    DG --> T3
    EC --> T3
    TF --> T3
    PM --> T3

    %% =====================  STYLING  =====================
    classDef llmBig    fill:#dbe7ff,stroke:#3a5fcd,stroke-width:2px,color:#000
    classDef llmMini   fill:#e5f3ff,stroke:#3a82cd,stroke-width:1px,color:#000
    classDef embed     fill:#fff4d6,stroke:#c2873f,stroke-width:1px,color:#000
    classDef ft        fill:#ffd6d6,stroke:#c23f3f,stroke-width:1px,color:#000
    classDef store     fill:#e6e6e6,stroke:#555,stroke-width:1px,color:#000
    classDef pipe      fill:#f5f5f5,stroke:#777,stroke-width:1px,color:#000
    classDef tab       fill:#dff5d6,stroke:#3f9c3f,stroke-width:2px,color:#000

    class DG,SCT llmBig
    class EC,RB,TF llmMini
    class PM,P04 embed
    class P05,FT ft
    class CSV,VDB store
    class P01,P01B,P02,P03 pipe
    class T1,T2,T3 tab
    class CORR,MAE pipe
```

## Reading guide for the grader

**Color legend**

| Color | Component type |
|---|---|
| 🟦 Dark blue | `gpt-4o` reasoning calls (narrative quality matters more than cost: gap diagnostic, opponent scouting) |
| 🟦 Light blue | `gpt-4o-mini` reasoning calls (cost-sensitive structured JSON output: contract estimates, target forecasts, roster builder) |
| 🟨 Yellow | OpenAI embedding work (`text-embedding-3-small`) — both the offline Batch API archetype classification and the runtime RAG retrieval |
| 🟥 Red | Together AI fine-tuned model (`Qwen/Qwen2.5-7B-Instruct` + LoRA r=64 α=128). **Eval only**, not runtime — the dedicated endpoint cold-start of ~4 min is unsuitable for an interactive Streamlit app |
| ⬜ Gray | Pipelines and storage |
| 🟩 Green | User-facing Streamlit tabs |

**Determinism guarantees on every reasoning call**

- `temperature=0`
- `seed=42` (where the model supports it)
- `response_format={"type": "json_object"}` for all structured-output calls
- Together inference uses `temperature=0` (response_format and seed are omitted because the fine-tuned model emits JSON natively from training and not all Together hosts honor those parameters)

**No-look-ahead enforcement**

- Contracts filtered by `signed_year <= evaluation_year` at every retrieval point
- Vector-store profiles filtered by `signed_year <= evaluation_year` in `player_matcher.find_matches`
- Fine-tune training data filtered per-row: each example's comparable pool only contains contracts with `signed_year < target_signed_year`
- Held-out evaluation set (26 contracts) shares the `random.seed(42)` selection between `eval/contract_mae.py` and `pipelines/05a_finetune_submit.py` so the same 30 indices are excluded from training and held out for scoring

**RAG flow specifically**

1. User selects a team + position gap on the Gap Filler tab
2. `diagnose_gaps_llm` (gpt-4o) returns a ranked list of gap positions with reasoning
3. For each gap, the reasoning text is embedded via `text-embedding-3-small` and used as a similarity query into the ChromaDB vectorstore
4. ChromaDB returns top-k candidates whose archetype + stats best match the gap, **filtered by position + signed_year ≤ evaluation_year**
5. Candidates pass to `forecast_target_contract_llm` (gpt-4o-mini at runtime, or the fine-tuned Qwen 7B on Together AI for the offline MAE eval)
6. The Gap Filler tab renders the gap + the top-3 candidates + per-target contract forecast

**Why the fine-tune is eval-only**

The Together-hosted Qwen 2.5 7B fine-tune (`rpeugh_302d/Qwen2.5-7B-Instruct-sabercast-contract-663bd032`) lives on a non-serverless tier of Together's account. Inference requires deploying a dedicated 2× H100 endpoint at $0.22/min, with a ~4 min cold-start. That latency profile is fundamentally incompatible with the interactive Streamlit-Cloud UX (target end-to-end response ≤ 12 s). The fine-tune therefore serves as a published held-out MAE benchmark (BUILD_LOG Entry 15) rather than a runtime path. The runtime forecast call uses `gpt-4o-mini` as the deployed forecaster; the `use_finetuned` kwarg on `forecast_target_contract_llm` is the routing seam that lets the offline eval swap in the fine-tune.

**Vendor-risk note (full story in BUILD_LOG Entries 14 + 15)**

The architecture had to absorb three mid-build LLM-platform constraints:

1. May 31: OpenAI deprecated self-serve fine-tuning for this organization
2. June 1 am: Together moved smaller Llama / Mistral models off the serverless tier
3. June 1 (later): Together flagged custom fine-tunes as non-serverless on this account tier, forcing dedicated-endpoint deployment with `endpoint.name` (not `model_output_name`) as the routing key

All three are documented as honest findings in the report's "Vendor risk" section. The runtime architecture above is the version that survived all three.
