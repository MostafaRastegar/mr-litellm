# Analytics Scripts

This folder contains scripts used for reporting, ROI, and dollar-cost calculations based on LiteLLM's metrics database.

- `savings_report.py` — reads the local `token_saver_metrics.jsonl` stream and prints aggregated byte/token/dollar savings.
- `savings_by_key.py` — queries LiteLLM's database directly and reports savings broken down by virtual key over a time range.

Usage:
```bash
# From a saved log stream
cat token_saver_metrics.jsonl | python3 tools/analytics/savings_report.py -

# Direct database query per key
export LITELLM_MASTER_KEY=sk-...
python3 tools/analytics/savings_by_key.py --days 7
```
