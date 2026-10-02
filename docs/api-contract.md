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
| `POST /consultations/{id}/review` | `{expectedRowVersion, inputRevision, predictionRunId, decisions, careNotes, prescription?}` | `200 {review}` | Assigned doctor; current `PENDING_DOCTOR_REVIEW` case. Decision target codes remain evidence-bound. |
| `POST /consultations/{id}/request-information` | `{expectedRowVersion, reason, requestedFields?}` | `200 {consultation}` | Assigned doctor; reviewable case. |
| `POST /consultations/{id}/approve` | `{expectedRowVersion, reviewId}` plus idempotency key | `201 {approval}` | Assigned doctor; current completed review only. |
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
