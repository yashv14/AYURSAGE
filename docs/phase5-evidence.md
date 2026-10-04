# Phase 5 implementation and evidence — 4 October 2026

**Acceptance incomplete. Live inference remains disabled.** Repository origin is
`https://github.com/yashv14/AYURSAGE.git`. Branch `phase5/frozen-inference` starts at
`d98e9e5`, which contains the Phase 4 implementation (`16a5b94`, `44b633a`) and supplied
source. Existing `.review-phase4` work was preserved. No existing database was used.

## Supplied evidence

- Original local artifact: `ml/artifacts/ayursage_model.pkl`, ignored by `*.pkl`.
- User-authorized artifact SHA-256:
  `e0b60420eaf618e165822af5f69f8c437794c06ae0ca885e5d68df8e6a9a7c98`.
- Original source: `ml/source/AyurSage_Training_v17.py`, preserved unchanged.
- Recorded source SHA-256:
  `afc2fb4b771467e3a47045b1c3b76f9dc898716078fc47d8f930bfb5093088d3`.

Static review found automatic pip installation, plotting, training, dataset reads,
artifact writes and demo behavior in the original training module. It is never
imported by the application or audit harness. `scripts/extract_v17.py` selects only
17 named constants/functions through AST inspection and reproduces the checked-in
`backend/app/v17_callable.py`. Verification compares exact parsed syntax trees to
avoid Python patch-version changes in AST formatter quote style; original source
bytes remain checksum-bound. Only `random.seed(seed)` changes to an invocation-local
`random = Random(seed)`; subsequent choices preserve their original sequence.
`predict_single()` invokes the fitted transform, four selected classifiers,
existing engine mappings and reasoning exactly once. Its optional confidence fields
are retained as returned; missing probabilities are never manufactured. The doctor
prescription slot remains the original `PENDING_DOCTOR_REVIEW` placeholder.

The checksum is verified on the bytes actually passed to joblib, avoiding a reopen
race. Bundle validation confirmed `AyurSage_v17`, one global `XGB` family, four
XGBClassifier instances, fitted ColumnTransformer/OneHotEncoder, four fitted label
encoders, exact feature/target ordering and exact lifestyle/yoga mappings from source.
Nine invalid bundle mutations were rejected. Version-mismatch warnings block loading.

The exact input order is:

1. Disease
2. Symptom Severity
3. Nadi Reading
4. Constitution/Prakriti
5. Stress Levels
6. Sleep Patterns
7. Age Group
8. Physical Activity Levels
9. BP Systolic
10. BP Diastolic
11. Pulse Rate
12. Weight (kg)

The four target identifiers are Herbal Therapy Strategy, Lifestyle Recommendations,
Therapeutic Yoga Module and Follow-up Recommendation. Fitted vocabularies are model
evidence, not approved clinical collection categories. Reasoning text mentions BP in
mmHg and the weight field names kg; reviewed units, precision and clinical bounds for
all numerical fields remain absent. No threshold in the source becomes API validation.

## Runtime and parity scope

The separate `.venv-v17-audit` environment inherited already installed packages;
no model dependencies were installed, pinned or changed. Tested successfully:

| Component | Tested version (not proof of original training environment) |
|---|---|
| Python | 3.12.7 |
| numpy | 2.4.6 |
| pandas | 3.0.3 |
| scipy | 1.18.0 |
| scikit-learn | 1.9.0 |
| joblib | 1.5.3 |
| xgboost | 3.3.0 |

The source can write training metadata but that file was not supplied. No original
Python version or complete training dependency lock is verified. Passing this audit
does not authorize these versions as production pins.

`scripts/audit_v17.py` executes an allowlisted AST of the original functions/constants,
excluding all imports, training and demo execution. Complete returned dictionaries
matched exactly for three unapproved candidates based on the demo, including all
categories, actual confidence/probabilities, reasoning, lifestyle, yoga and placeholder.
Sixty concurrent calls across eight threads matched sequential original results and
left the process-global random state unchanged. Sequential adapter calls measured
approximately 10–15 ms locally; this is not a production timeout or load guarantee.

The original demo's Disease value `Diabetes Mellitus Type 2` is absent from the fitted
vocabulary. Its complete output still matched, but it is **not a valid API candidate**.
The three validated audit candidates explicitly use the artifact-evidenced spelling
`Diabetes Mellitus (Type 2)`; this is not an automatic conversion. Numeric variants
are test candidates, not approved boundaries. No expected owner-approved outputs or
clinical validity are claimed. The harness prints audit summaries, never clinical results.

## Application behavior

`ML_ENABLED=false` remains mandatory. The factory constructs one worker-local disabled
inference component and checks artifact integrity without deserializing it. Neither
config nor a model_versions row can bypass missing evidence. The loader and callable
are available for explicit audit only; a production enabled runtime is deliberately
deferred until evidence approval and bounded processing policy exist.

Platform readiness retains its existing database/migration meaning, and reports
`ml: unavailable` with safe operational `mlBlockers` codes. Filesystem paths and
exception details are excluded. A matching checksum does not mean ML readiness.

`POST /api/v1/consultations/{id}/submit` requires the owning active patient,
`{expectedRowVersion, inputRevision}`, a current eligible draft/information revision,
and `Idempotency-Key`. With the current evidence gate it returns `503 ML_UNAVAILABLE`
and leaves the draft and revision unchanged. Invalid/stale requests are rejected
before inference. A future verified service must validate clinical schema/provenance
before entering the internal persistence operation; no accepted clinical schema is
invented in this change.

The internal persistence path is exercised only with synthetic mocked services:
it optimistically writes the consultation before prediction, marks the input submitted,
binds one run to that revision/model and atomically writes all four raw outputs and
the deterministic enrichment in separate tables. Success becomes
`PENDING_DOCTOR_REVIEW`. Failures record a safe failed run without outputs; storage
failure rolls back the entire submission. Duplicate keys replay the run, do not
rerun failed inference, and reject conflicting request versions. Adapter/source
provenance is stored in the run-linked immutable audit and checked model evidence.
Used model provenance, enrichment and raw outputs cannot be rewritten through ORM.

`GET /api/v1/consultations/{id}/predictions` permits only the active assigned doctor
and requires a complete successful current pending-review run. Patients cannot read
pending predictions. The future doctor's decisions are separate; no review, approval,
prescription generation or report release is implemented.
`POST .../prediction-runs` checks doctor assignment but returns
`503 RETRY_POLICY_UNAPPROVED`; no retry authority is invented.

SQLite mocked tests establish local service behavior, not MySQL locking/concurrency
or real clinical-contract validation. The real audit is opt-in and separate from CI's
mocked tests. Real MySQL concurrency, approved validation, recovery/timeouts and
authorized retry execution remain acceptance work.

Local checks passed: 42 default tests (two MySQL tests and the opt-in real-model test
skipped in that invocation), frontend `npm run check`, foundation safety guard and
`git diff --check`. The existing disposable MySQL migration/integrity suite separately
passed both tests using a unique Docker project, which was removed afterwards. That
suite proves existing schema integrity, not the new inference workflow's concurrent
MySQL transaction behavior. The real-model audit separately passed the scope above.

## Evidence checklist and local placement

Supply these as synthetic/non-sensitive evidence; never supply patient cases or
credentials in Git. Filenames below are proposed evidence locations, not proof that
their contents exist or have been approved.

- [ ] `ml/evidence/training-environment.json`: original Python/package versions,
  original training metadata and provenance tying them to this exact checksum.
- [ ] `ml/evidence/training-requirements.lock`: original complete dependency lock or
  equivalent export. Do not regenerate it from this tested audit environment.
- [ ] `ml/reference_cases/authorized-v17.json`: owner-approved synthetic inputs and
  full expected outputs, case authorization/provenance, model/source checksums and
  numeric comparison rules where applicable. Resolve the demo Disease mismatch.
- [ ] `ml/evidence/input-contract.json`: reviewed exact schema version, vocabularies,
  numeric types/units/precision/bounds, missing/unknown policy and provenance requirements.
- [ ] `docs/clinical-input-policy.md`: clinic-approved Disease/Nadi/Prakriti collection
  and verification authority, approving owner/date and required provenance.
- [ ] `docs/enrichment-policy.md`: required engine semantics, limitations,
  contraindication/conflict/context and failure handling approval. Source reasoning
  is deterministic annotation; absence of a warning is not clinical clearance.
- [ ] `docs/inference-operations-policy.md`: authorized retries, attempt idempotency,
  timeout/recovery policy and bounded synchronous runtime acceptance. Provide
  disposable MySQL concurrency evidence before production enablement.

Another developer must obtain the original artifact through the authorized channel,
place it locally at `ml/artifacts/ayursage_model.pkl`, verify SHA-256 against the user
manifest above, and leave it ignored. Never force-add it. Keep original source intact.

For a reviewed audit environment that already contains its dependencies:

```powershell
Get-FileHash ml/artifacts/ayursage_model.pkl -Algorithm SHA256
.venv-v17-audit/Scripts/python.exe -I -c "import sys; sys.path.insert(0, '.'); from scripts.audit_v17 import audit; audit()"
```

For pytest real-model execution in that environment, explicitly set
`RUN_V17_REAL_MODEL_TESTS=1` and run `python -m pytest tests/real_model`. Default tests
skip real deserialization. No automatic package installation occurs in these commands.
