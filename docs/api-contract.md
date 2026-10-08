# AYUR-SAGE API contract outline

**Base path:** `/api/v1`

**Status:** Phase 2 transport design; no clinical/model schemas are executable until V17 evidence and clinical provenance decisions are approved.

## Common conventions

- JSON request and response bodies use explicit versioned schemas.
- Access authentication uses `Authorization: Bearer <access-token>`; refresh/logout use a protected HttpOnly cookie and origin/CSRF controls once implemented.
- Every protected route checks active account, primary role, resource relationship, and workflow state on the server.
- IDs are opaque strings in the API. Possessing an ID does not grant access.
- Collection routes are paginated with an opaque cursor and bounded `limit`.
- Mutating submit, processing, approval, and report operations require an `Idempotency-Key` or a database-enforced equivalent scoped to actor, operation, and revision.
- Stale mutation requests carry `expectedRowVersion` and receive `409 CONFLICT` when the aggregate changed.
- Timestamps are RFC 3339 UTC strings.

## Response envelopes

Successful single-resource response:

```json
{
  "data": {},
  "requestId": "opaque-request-id"
}
```

Safe error response:

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Safe human-readable summary",
    "fields": {}
  },
  "requestId": "opaque-request-id"
}
```

`fields` is optional and contains no secrets or unauthorized clinical content. Stack traces, SQL details, tokens, and raw dependency errors are never returned.

## Status-code policy

| Code | Use |
|---|---|
| `200` | Successful read or idempotent operation returning an existing result. |
| `201` | Resource/version created. |
| `204` | Successful operation with no response body. |
| `400` | Malformed request syntax. |
| `401` | Missing, invalid, or expired authentication. |
| `403`/`404` | Forbidden resource according to one consistently documented existence-hiding policy. |
| `409` | Stale row/revision, invalid state transition, or idempotency-key payload conflict. |
| `422` | Structurally valid JSON with invalid field values. |
| `429` | Throttled request. |
| `503` | Required dependency or verified model readiness unavailable. |

## Endpoint schemas

Fields below are application/transport fields. `clinicalInput` and raw `result` deliberately remain opaque objects until original V17 and clinic workflow evidence finalize their schemas.

| Method and route | Request schema | Success response | Authorization and state |
|---|---|---|---|
| `POST /auth/register` | `{email, password, acceptedTermsVersion}` | `201 {user}` | Public; always creates Patient role. |
| `POST /auth/login` | `{email, password}` | `200 {accessToken, expiresAt, user}` plus refresh cookie | Public, throttled; active account required. |
| `POST /auth/refresh` | Empty body plus refresh cookie/origin proof | `200 {accessToken, expiresAt}` with rotated cookie | Valid unrevoked refresh session. |
| `POST /auth/logout` | Empty body plus refresh cookie/origin proof | `204` | Revokes current refresh chain. |
| `GET /auth/me` | None | `200 {user}` | Authenticated active account. |
| `GET /patients/me` | None | `200 {patient}` | Patient owns profile. |
| `PATCH /patients/me` | `{expectedRowVersion, changes}` | `200 {patient}` | Patient; allowlisted non-clinical profile fields. |
| `POST /consultations` | `{idempotencyKey?, context?}` | `201 {consultation}` | Patient creates own `DRAFT`; no fabricated clinical defaults. |
| `GET /consultations` | Query `{cursor?, limit?, state?}` | `200 {items, nextCursor}` | Role-scoped results only. |
| `GET /consultations/{id}` | None | `200 {consultationView}` | Owning patient or assigned doctor; response fields differ by role. |
| `PUT /consultations/{id}/inputs` | `{expectedRowVersion, schemaVersion, clinicalInput, provenance}` | `201 {inputRevision, consultation}` | Owning patient in `DRAFT`/`NEEDS_INFORMATION`, or assigned doctor only under approved correction policy. Exact clinical schema blocked. |
| `POST /consultations/{id}/submit` | `{expectedRowVersion, inputRevision}` plus idempotency key | `200 {consultation, processingStatus}` | Owning patient; eligible current revision. |
| `POST /consultations/{id}/prediction-runs` | `{inputRevision, reason}` plus idempotency key | `201 {predictionRun}` | Internal/explicitly authorized retry policy; never a detached public prediction endpoint. Returns `503` while V17 unavailable. |
| `GET /consultations/{id}/predictions` | None | `200 {run, originalOutputs, enrichment}` | Assigned doctor only; patient cannot read pending raw output. |
| `POST /consultations/{id}/review` | `{expectedRowVersion, expectedReviewRevision, inputRevision, predictionRunId, decisions, careNotes, careNotesCompleted, prescription?}` | `201 {review, consultation}` | Active verified assigned doctor; current `PENDING_DOCTOR_REVIEW` case. Each save creates a new review revision. |
| `POST /consultations/{id}/request-information` | `{expectedRowVersion, reason, requestedFields?}` | `200 {consultation}` | Assigned doctor; reviewable case. |
| `POST /consultations/{id}/approve` | `{expectedRowVersion, reviewId, reviewRevision}` plus idempotency key | `201/200 {approval}` | Assigned doctor; current completed review and verified clinical policy required. Currently gated with 503. |
| `POST /consultations/{id}/reject` | `{expectedRowVersion, reason}` | `200 {consultation}` | Assigned doctor; reviewable case; reason required. |
| `POST /consultations/{id}/reports` | `{approvalId, reportVersion}` plus idempotency key | `201/200 {report}` | Owning patient or assigned doctor for approved version; retry reuses identity. |
| `GET /reports/{id}/download` | None | PDF stream | Owning patient or assigned doctor; report `READY`; no public caching. |
| `POST /consultations/{id}/attachments` | Bounded multipart metadata/content | `201 {file}` | Disabled until ownership, validation, limits, and scan/quarantine policy are implemented. |
| `PATCH /admin/users/{id}` | `{expectedRowVersion, operation, reason}` | `200 {user}` | Admin operational authority; controlled role/active operations only. |
| `POST /admin/consultations/{id}/assignment` | `{expectedRowVersion, doctorId, reason}` | `200 {assignment}` | Admin; operational metadata only; audit required. |
| `GET /health/live` | None | `200 {status: "ok"}` | Public, non-sensitive process liveness. |
| `GET /health/ready` | None | `200` or `503` safe component summary | Public/non-sensitive; must not claim ML readiness before verification. |

## Clinical input schema gate

### Application field constraints

These constraints apply to the outline above and do not define model fields:

- `expectedRowVersion` and `inputRevision` are positive integers; reject booleans,
  fractional values, and missing values on routes requiring them.
- Resource IDs and schema/report versions are nonempty opaque strings. The server
  resolves known versions; client-supplied versions cannot enable an unknown schema.
- `reason` is a nonempty string after whitespace validation. Length and body-size
  limits must be selected and enforced before these routes are implemented.
- Review `decisions` is an array of `{targetCode, action, content?, reason?}`.
  `action` is `ACCEPT`, `EDIT`, or `OVERRIDE`; edit/override require content and reason.
  Target identifiers and content types await evidence; completeness is checked against
  the verified target set, never against client-supplied counts.
- Unknown writable fields are rejected. Patient ownership, role, assignment,
  verification actor, and approval timestamps are server-controlled.
- Idempotency keys use the header consistently; the optional body field on creation
  is not a second authority. Reusing a key with a different payload returns `409`.
- Protected resource lookups outside ownership/assignment scope return `404`;
  role-forbidden operations without a resource lookup return `403`.

Successful resource representations expose only role-allowed fields. A consultation
includes `id`, `state`, `rowVersion`, nullable `currentInputRevision`, and safe processing
status. A new draft may have no input revision. Raw clinical payloads are excluded from
operational-admin projections. Collection responses wrap `{items, nextCursor}` in `data`.

The future `clinicalInput` schema must be generated from reviewed evidence, not this outline. It must specify exact feature keys/order mapping, types, accepted categories, numeric units/precision, finite-number checks, required/missing behavior, and provenance. Additional clinical context must use separate fields and must not enter the frozen model unless the original contract proves it does.

## Prediction response gate

Prediction storage/API mapping must preserve the callable's actual target identifiers, class identifiers/labels, and metadata. The API must not promise probabilities or confidence. Doctor-facing output stays unavailable until a complete successful run and required enrichment records exist. Patient-facing output stays unavailable until doctor approval.

## Phase 4 implemented subset

The identity, own-patient profile, consultation draft/input revision, administrator
doctor onboarding, and assignment routes above are implemented. Access JWTs use HS256
with configured issuer and short expiry. Refresh credentials are random opaque values;
only SHA-256 token fingerprints are stored. Every successful refresh revokes and
replaces the prior session. Use of a rotated token is treated as reuse and revokes its
replacement chain. Logout revokes the presented session and descendants.

Refresh and logout require an exact allowed `Origin`, a `SameSite=Strict` refresh
cookie scoped to `/api/v1/auth`, and double-submit CSRF proof. Deployments use Secure
cookies; local HTTP tests may explicitly disable Secure. Protected resource lookups
hide cross-patient and unassigned-doctor existence with `404`.

Input payload and provenance objects remain opaque and are never interpreted or sent
to ML. Each accepted draft change creates a new `clinical_inputs` revision; it does
not overwrite an older revision. Only `DRAFT` and `NEEDS_INFORMATION` are eligible.
The latter state is schema-supported but no transition into it is exposed because the
doctor request-information clinical policy belongs to a later phase.

## Phase 5 gated subset

Submission, assigned-doctor prediction viewing and a blocked retry route are now
present. Live submission returns `503 ML_UNAVAILABLE` without mutating the draft;
the supplied artifact/source/checksum do not bypass missing runtime, reference or
clinical-policy evidence. The internal atomic persistence path is tested with
synthetic mocked services only. Its successful result remains pending doctor review;
patients cannot read pending predictions. Retry returns
`503 RETRY_POLICY_UNAPPROVED`. Readiness adds safe `mlBlockers` codes while preserving
platform readiness semantics. See [Phase 5 evidence](phase5-evidence.md) for exact
transport, idempotency, provenance and acceptance limitations. No review, approval,
prescription generation or report-release operation is enabled.

## Phase 6 implemented transport

Phase 6 supersedes the Phase 5 statement about review/approval routes above. Live
inference remains gated; live approval also requires the missing clinical policy.
The full implementation and acceptance boundaries are documented in
[Phase 6 acceptance](phase6-acceptance.md).

Additional routes:

| Route | Response and scope |
|---|---|
| `GET /doctor/review-queue?limit=25&cursor=...` | Active verified doctor's assigned pending consultations. `limit` is 1–100; opaque UUID cursor; `{items,nextCursor}`. |
| `GET /consultations/{id}/review-context` | Assigned doctor only; consultation version, exact input/run, original outputs including actual optional confidence, deterministic enrichment, safe provenance and latest review. |
| `GET /consultations/{id}/review?revision=N` | Assigned doctor only; latest review by default, or an exact historical positive review revision. |
| `GET /consultations/{id}/approved` | Owning patient or assigned doctor; approved patient projection only, with approval identity/version/timestamp. No raw confidence or internal review history. |
| `GET /consultations/{id}/information-request` | Owning patient or assigned doctor in `NEEDS_INFORMATION`; doctor-authored reason and requested input fields. |

Review save is a full draft replacement expressed as a **new** revision. Initial
`expectedReviewRevision` is 0; later saves must match the latest revision. The
consultation's `expectedRowVersion` must also match. A new review ID is returned for
each save. Save responses include the updated consultation version. Missing/unknown
fields, duplicate targets and non-integer/boolean versions are rejected.

`decisions` may be partial while drafting; each item is `{targetCode,action}` for
ACCEPT or `{targetCode,action,content,reason}` for EDIT/OVERRIDE. `content` is nonblank
doctor-authored text (maximum 16,000 characters), and change reasons are nonblank text
(maximum 2,000). ACCEPT cannot include a client replacement/reason. No clinical
category or medication schema is inferred from these free-text transport fields.

`careNotes` is text (maximum 16,000 characters; may be blank in an incomplete draft).
`careNotesCompleted` is an explicit boolean. True requires nonblank notes.
`prescription` is optional nonblank doctor-authored text (maximum 16,000 characters)
or null. The exact V17 pending-review placeholder is rejected. All four target
decisions plus completed care notes derive COMPLETED status; clients cannot set status.
Review API bodies are limited to 128 KiB and responses use `Cache-Control: no-store`.

Approval first creation returns 201; an authorized exact replay returns 200. The
idempotency key is scoped to actor/consultation/approval operation and fingerprints
all three request fields. A conflicting key/body or stale state/revision returns 409.
Otherwise valid live attempts currently return `503 CLINICAL_REVIEW_POLICY_UNAPPROVED`.
Patients/admins receive 403; unassigned doctors receive 404. No request field or
environment flag can enable missing policy or inference evidence.

`POST .../request-information` implements the outlined assigned-doctor transition.
It requires `expectedRowVersion` and nonblank `reason` (maximum 2,000 characters).
Optional `requestedFields` is a unique array of the evidenced Phase 5 input names.
It returns `201 {consultation,informationRequestId}`, supersedes prior eligible
reviews, and preserves the submitted input. The patient input route creates a new
revision. No post-approval correction or amendment route is enabled. The Phase 7
report routes below supersede this Phase 6 record's earlier report limitation.

## Phase 7 report transport

All routes require an active owning patient or active verified assigned doctor.
Admins receive 403; outside ownership/assignment scope receives 404. The consultation
must be APPROVED and the exact approval snapshot must pass integrity/provenance
checks. Report generation never invokes inference or creates an approval.

| Route | Request / response |
|---|---|
| `POST /consultations/{id}/reports` | Exact body `{approvalId, reportVersion: "approved-patient-v1"}`. Approval/version uniqueness is the database-enforced idempotency equivalent. First success 201, existing READY or recovered retry 200, active generation lease 409 `REPORT_GENERATING`. Unknown fields/versions 422. No client paths, template flags or synthetic bypass. |
| `GET /reports/{id}` | 200 `{report}` containing opaque ID, approval ID, report/template version, snapshot checksum, lifecycle status, safe failure code, retry count and file checksum when recorded. READY metadata is returned only after current file integrity verification. No storage keys, paths or URLs. |
| `GET /reports/{id}/download` | Backend PDF attachment, safe `ayursage-report-{UUID}.pdf` filename, `application/pdf`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. File size/checksum and authorization verified before returning bytes. No public URL, SAS, conditional caching or range-download API. |

Missing/nonapproved resources return 404. Invalid snapshot/provenance, unavailable
storage, failed generation, non-READY file or mismatched file integrity return safe
503 codes. Approval-state/idempotency semantics are independent of report recovery;
failure never invalidates or modifies an approval. See
[Phase 7 storage and recovery](phase7-reports.md) for lease/reconciliation details.
