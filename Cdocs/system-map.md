# System map

## Runtime today

```text
Operator / caller → main.py or ingest(paths) → multi-format native-text intake → one TAMU extraction → Invoice schema gate
                                                                                 ↘ report + events + result artifacts
```

Ingestion returns a typed handoff. Validation remains a separate package; the CLI does not automatically run it. Critic/revision loops, deterministic ingestion normalization, image-only PDF/OCR, graph routing, and LangSmith tracing are not in the POC runtime.

## Code map

| Location | Responsibility |
| --- | --- |
| `main.py` | CLI input selection and human-facing result paths. |
| `ingestion/ingest.py` | One-pass orchestration and terminal status mapping. |
| `ingestion/extraction.py` | Bounded PDF/TXT/JSON/CSV/XML reading and native-text locators. |
| `ingestion/providers.py` | One TAMU structured extraction request. |
| `ingestion/artifacts.py` | JSON snapshots, event stream, and Markdown run report. |
| `validation/` | Separate downstream validation implementation. |
