# Dataset schema and official-data validation

Official Integraminds data was **not available** during development. Every number in this repository comes from
synthetic data. This document defines the expected input files so validation runs as soon as the files are supplied.

## Where to put the files

`data/official/` (git-ignored, never committed). Files are read-only for the pipeline; their SHA-256 hashes are recorded.

| File | Required | Content |
|---|---|---|
| `DATASET.json` | yes | provenance: `name`, `version`, `provider`, `license`, `synthetic` (false for official data); optional `notes`, `data_dictionary` |
| `item_bank.csv` or `.jsonl` | yes | one row per item (below) |
| `response_logs.csv` | yes | one row per candidate × item (below) |
| `leak_posts.jsonl` or `.csv` | no | authorised leak dataset: `post_id`, `channel`, `channel_type`, `posted_at` (ISO 8601 UTC), `text` |
| `leak_labels.csv` | no | ground truth for metrics: `item_code`, `leaked` (0/1), `leak_type`, `leak_first_slot`, `split` (`dev` or `heldout`) |

### item_bank columns
`item_code` (unique), `section` (QUANT|LOGICAL|VERBAL), `stem`, `option_a`…`option_d`, `correct_option` (A–D);
optional `difficulty` (easy|medium|hard, default medium), `skill`, `concept`, `family_code`, `parent_code` (source item
of a variant), `explanation`.

Import policy: rows with structural errors (missing/duplicate key, identical options, unknown difficulty) are **rejected**
with reasons. Rows that duplicate another item are **imported but held** as `pending_review` (they were administered, so
dropping them would lose response data) and are excluded from assembly until reviewed.

### response_logs columns
Required: `slot_code`, `form_code`, `candidate_ref`, `item_code`, `selected_option` (A–D or blank = omitted).
Optional: `drive`, `slot_sequence`, `slot_start` (ISO 8601), `is_correct` (checked against the bank key; mismatches
reported), `response_time_ms`, `position`, `submitted_at`. Every `item_code` must exist in the bank (all-or-nothing:
otherwise the import is refused with the offending codes listed).

## Run

```bash
backend/.venv/bin/python scripts/validate_official_data.py
```

Exit code `3` with `"status": "BLOCKED"` means inputs or provenance are missing; the message lists exactly what.
The run uses a fresh temporary database (or `--database-url` pointing at an empty database named `*_validation`),
the frozen default policies (their hash is in the report), and writes `reports/official-validation/<timestamp>/report.json`
and `REPORT.md`.

## Scientific rules enforced by the pipeline
- No threshold tuning happens in this command. If `leak_labels.csv` has a `split` column, metrics are reported per split
  and **only `heldout` may be quoted as independent validation**.
- Leak metrics (precision, recall, false-positive/negative rate, per leak type, detection latency) carry Wilson 95% CIs.
- Calibration reports insufficient-data and inconclusive cases explicitly; equivalence requires the TOST criterion.
- Assembled forms are re-verified from the stored manifests (overlap, families, eligibility), independently of the solver.

## Pipeline check with synthetic data (not validation)

```bash
backend/.venv/bin/python scripts/make_synthetic_validation_fixture.py /tmp/aptiguard-fixture
```

```bash
backend/.venv/bin/python scripts/validate_official_data.py --data-dir /tmp/aptiguard-fixture --out /tmp/aptiguard-report
```

The fixture declares `synthetic: true`, so the report is titled "SYNTHETIC PIPELINE CHECK — NOT OFFICIAL VALIDATION",
and its labels are `split=dev` because the detection thresholds were developed on that same scenario.
