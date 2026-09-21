# Validation Evaluation

Run with `python main.py --eval-validation`. The evaluator reconstructs trusted `IngestionResult` values from ingestion goldens, so this suite isolates validation from source extraction.

Semantic runs first. Cases with expected Semantic denial stop there; passing cases may continue through Reconciliation and Database. Comparisons include stage status, denial stage, issue codes and fields, critic completion, revision counts, Decimal calculations, consolidation, identity mappings, product coverage, requested quantity, stock, and final route.

The compatibility flags `--eval-semantic` and `--eval-reconciliation` invoke this same full evaluator. They are not separate production graphs.
