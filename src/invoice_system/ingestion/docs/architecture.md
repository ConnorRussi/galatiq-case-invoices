# Runtime architecture

```text
PDF/TXT/JSON/CSV/XML → native-text extraction → one provider call → Invoice schema gate → artifacts
```

There is no graph, retry, critic, revision, business normalization, or business validation. PDFs must have usable native text; visual/OCR processing is intentionally absent.
