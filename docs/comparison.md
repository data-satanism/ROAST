# Comparison and showcase ingestion

Comparison APIs consume only the portable BMF-106 schema. They do not rewrite
model names or inspect solution-specific strings.

- `load_run_directory(path)` loads one portable run.
- `load_artifact_root(path)` follows `_registry/run_registry.jsonl`.
- `build_leaderboard(result, metric_id)` returns deterministic model scores and ranks.
- `build_mean_ranks(results, metric_id)` averages model ranks across runs.
- `build_pairwise_deltas(left, right, metric_id)` aligns item-level records and
  reports both raw delta and direction-aware improvement.
- `build_comparison_table(results, metric_id)` produces stable multi-run rows.

Stable row fields are intended for CSV/dataframe conversion by consumers. Metric
direction comes from BMF-105 record metadata rather than task-name switches.

## Showcase manifest

Showcase ingestion is configuration-driven:

```json
{
  "format": "roast_showcase@1",
  "schema_version": 1,
  "runs": [
    {
      "artifact_root": "../benchmark-results",
      "run_id": "toy-1234",
      "display_name": "Toy baseline"
    }
  ]
}
```

Relative artifact roots resolve from the manifest directory. Display names are
used exactly as supplied; core has no alias table. `load_showcase(path)` returns
`(display_name, BenchmarkResult)` pairs ready for the comparison builders.
