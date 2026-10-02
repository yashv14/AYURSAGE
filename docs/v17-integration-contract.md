# Frozen V17 integration evidence and contract

**Status:** Blocked pending original materials

**Audit date:** 2 October 2026

This document records what the repository proves today, what the supplied architecture reports, and what must be verified before V17 inference can be enabled. Reported claims are not treated as an executable contract until supported by original evidence.

## Evidence inventory

A complete repository filename and content inspection found none of the following:

- `ayursage_model.pkl` or another serialized model artifact;
- a `predict_single()` implementation or its helper modules;
- a training or inference notebook/script;
- model metadata, checksum, trusted manifest, or provenance record;
- Python/model dependency evidence;
- encoders, preprocessors, datasets, label maps, or class lists;
- authorized synthetic reference inputs and expected outputs; or
- Clinical Reasoning, Lifestyle, or Yoga engine source/configuration.

At the Phase 2 inventory, the Python code consisted of the Flask shell and its liveness test.
Phase 3 adds application persistence and infrastructure tests, without supplying any
of the original ML materials above. ML integration stays unavailable and
`ML_ENABLED=false` remains the only supported setting.

## Evidence classification

| Item | Current classification | Consequence |
|---|---|---|
| V17 is frozen | Governing requirement | Do not retrain, refit, reconstruct, or substitute it. |
| `predict_single()` is the intended boundary | Reported by architecture; callable absent | Do not create an implementation or adapter signature yet. |
| Twelve inputs and four outputs | Reported by architecture; source unverified | Do not encode names, order, categories, units, labels, or validation rules in runtime code. |
| XGBoost selection and reported metrics | Reported experimental claim; evidence absent | Do not add XGBoost or present metrics as reproduced. |
| Enrichment engines exist | Reported requirement; source absent | Do not recreate rules or claim contraindication handling. |
| Model dependencies | No evidence | Do not add guessed ML packages or versions. |

## Contract fields awaiting evidence

The eventual contract document must fill every field below directly from original materials. Every unavailable value is an explicit integration blocker, not an application default.

| Contract field | Required evidence | Current value |
|---|---|---|
| Artifact filename and byte size | Original artifact | Unavailable—artifact not supplied |
| Artifact SHA-256 | Trusted independently reviewed manifest | Unavailable—manifest not supplied |
| Artifact/version identifier | Original release record | Unavailable—release record not supplied |
| Python version | Original environment/lock evidence | Unavailable—runtime evidence not supplied |
| Package names and versions | Original environment/lock evidence | Unavailable—dependency evidence not supplied |
| Callable import path | Original source | Unavailable—source not supplied |
| Function signature | Static inspection of original source | Unavailable—source not supplied |
| Input container and feature order | Source plus reference cases | Unavailable—source/cases not supplied |
| Category vocabulary and unknown policy | Fitted preprocessing/source | Unavailable—preprocessor/source not supplied |
| Numeric types, units, precision, ranges | Source/data dictionary | Unavailable—data dictionary not supplied |
| Missing-value behavior | Source plus reference cases | Unavailable—source/cases not supplied |
| Return container and target identifiers | Source plus reference output | Unavailable—source/output not supplied |
| Class identifiers and labels | Fitted artifact/source | Unavailable—artifact/source not supplied |
| Confidence/probability fields | Actual callable output | Unavailable—callable output not supplied |
| Randomness and thread behavior | Source and repeated execution | Unavailable—source/runtime not supplied |
| Error behavior | Source and controlled negative cases | Unavailable—source/runtime not supplied |

No unavailable value may be guessed into an accepted API value, model default, or database seed.

## Required static inspection before import

Before importing any supplied Python module:

1. Preserve the received files read-only and record provenance, byte size, and SHA-256.
2. Review imports and top-level statements for training, fitting, resampling, dataset reads, network calls, writes, plotting, or model replacement.
3. Trace `predict_single()` and all direct helpers to identify preprocessing, feature order, return construction, global state, randomness, and enrichment calls.
4. Identify all files and environment variables read at import and call time.
5. Record deserialization mechanism and verify that only the trusted artifact can reach it.
6. Stop if import triggers training or mutates the frozen artifact; design an import-safe extraction that preserves behavior and obtain review before execution.

Serialized Python models are executable trust boundaries. They must not be loaded merely to discover whether they are safe.

## Runtime boundary once verified

The future adapter has one responsibility: translate an already validated, versioned application snapshot into the exact evidenced callable input; invoke the original callable once; and serialize its actual return without relabeling or inference logic. It must not:

- fit, transform with a newly fitted object, resample, select a model, or regenerate labels;
- silently fill missing clinical values;
- accept categories merely because an encoder tolerates unknowns;
- derive or invent probabilities;
- combine raw output with doctor-authored content; or
- expose a patient-callable prediction endpoint outside a consultation revision.

Raw output, deterministic enrichment, and doctor review will be persisted as separate provenance layers even if the original callable currently combines them.

## Engine boundary audit

Each supplied engine requires a separate evidence record:

| Evidence question | Clinical Reasoning | Lifestyle | Yoga |
|---|---|---|---|
| Source/configuration received | No | No | No |
| Import/call entry point known | No | No | No |
| Exact inputs known | No | No | No |
| Exact outputs known | No | No | No |
| Execution order known | No | No | No |
| Invoked inside `predict_single()` known | No | No | No |
| Contraindication/context behavior known | No | No | No |
| Conflict behavior known | No | No | No |
| Failure behavior known | No | No | No |
| Version identifier known | No | No | No |

Until source evidence answers these questions, each engine is unavailable. An engine failure must eventually remain an explicit failed enrichment result and must not be represented as successful or guessed content.

## Reference-test plan

Reference tests begin only after authorized synthetic cases and a verified runtime are available.

1. Store synthetic inputs and expected outputs in `ml/reference_cases/`; do not store patient data.
2. Bind each fixture set to the trusted artifact checksum, callable source revision, runtime lock, and engine versions.
3. Include at least one known-good case from the original owners and evidence-supported boundary cases. Do not manufacture categorical values merely for coverage.
4. Compare the complete returned structure and values. Use exact comparison for identifiers/labels and evidence-defined numeric tolerances only where the original output is numeric.
5. Run repeated calls to detect state mutation or seeded/unseeded variability.
6. Run negative cases for missing fields, unsupported evidenced categories, non-finite numbers, and wrong types outside the frozen callable, at the adapter validation boundary.
7. Test that a run cannot be marked successful unless the evidenced complete target set is persisted atomically.
8. Execute each supplied deterministic engine once in isolation and once in the evidenced order, retaining raw prediction output separately.
9. Fail readiness on checksum, metadata, import, reference-output, or required-engine validation failure.

Parity success proves only software consistency with the frozen artifact. It does not establish clinical validity.

## Unblocking checklist

- [ ] Original artifact delivered through a trusted channel.
- [ ] Original callable and all helper/configuration files delivered.
- [ ] Original runtime/dependency evidence delivered.
- [ ] Trusted checksum approved independently of the artifact location.
- [ ] Authorized synthetic reference cases and expected raw outputs delivered.
- [ ] Engine source/configuration and expected results delivered.
- [ ] Static import-safety review completed.
- [ ] Exact contract fields above reviewed and resolved.
- [ ] Parity tests pass in the evidenced environment.
- [ ] Runtime readiness remains false until every required check passes.
