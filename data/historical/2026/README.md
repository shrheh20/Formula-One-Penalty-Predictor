# 2026 Historical Dataset

This directory stores the precomputed JSON payloads used by the `Past Races`
experience.

Generate or refresh the dataset with:

```bash
./.venv/bin/python build_historical_2026_dataset.py --year 2026 --force
```

The FastAPI backend reads from these files before attempting any runtime
FastF1 generation.
