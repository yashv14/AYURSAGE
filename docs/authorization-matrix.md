# Role, ownership, and assignment matrix

Authorization is enforced by backend services for every operation. Frontend visibility is only a usability layer. “Own” means the authenticated patient account is related through its unique patient profile; “assigned” means the active doctor assignment on the consultation matches the authenticated active doctor account.

| Operation | Patient | Assigned doctor | Unassigned doctor | Admin | Additional conditions |
|---|---|---|---|---|---|
| Register public account | Yes | N/A | N/A | N/A | Registration always creates Patient; client cannot choose role. |
| View/update account basics | Own | Own | Own | Own | Allowlisted fields; active account. |
| View/update patient profile | Own | Assigned-case minimum view only | No | No by default | Clinical content minimized by purpose. |
| Create consultation | Own profile | Only if later explicitly enabled | No | No by default | Starts `DRAFT`; no clinical defaults. |
| List/view consultation | Own | Assigned | No | Operational metadata only by default | Role-specific response projection. |
| Edit draft input | Own `DRAFT` | Only under approved clinic policy | No | No | Expected row version and provenance recorded. |
| Correct requested input | Own `NEEDS_INFORMATION` | Only under approved clinic policy | No | No | Creates new revision; never overwrites submitted input. |
| Submit revision | Own | Only under approved on-behalf policy | No | No | Current eligible revision plus idempotency. |
| Trigger initial inference | Indirectly through submit | No direct arbitrary call | No | No | Service-owned consultation processing; V17 must be ready. |
| Retry failed inference | No by default | Assigned if policy enables | No | Operational trigger only if policy enables | Same eligible revision; creates new run; audited. |
| View pending raw prediction | No | Assigned | No | No by default | Current/authorized historical case only. |
| View enrichment details | No while pending | Assigned | No | No by default | Explicit engine status/failure shown. |
| Request information | No | Assigned | No | No | Reviewable case; reason required. |
| Accept/edit/override target | No | Assigned | No | No | Current run; reason required for edit/override. |
| Write care notes/prescription | No | Assigned | No | No | Care notes completion required; medication optional. |
| Approve/reject | No | Assigned | No | No | Current revision/review; expected row version; all approval invariants. |
| View approved decision | Own released version | Assigned | No | No by default | Approved snapshot only. |
| Generate/retry report | Own approved version under policy | Assigned | No | No by default | Same immutable approval/report identity. |
| Download report | Own released report | Assigned | No | No by default | `READY`; authorization checked on each stream request. |
| Upload/view attachment | Own scope if enabled | Assigned if cleared | No | No by default | Disabled until validation and scan/quarantine policy exists. |
| Assign/reassign doctor | No | No | No | Yes | Operational metadata only; qualified active doctor; reason/audit required. |
| Create/activate doctor | No | No | No | Yes | Onboarding/verification gate; no public privilege grant. |
| Grant/revoke Admin | No | No | No | Controlled admin operation | Bootstrap/recovery process and audit required. |
| View operational health | No | No | No | Yes | Public health may expose only non-sensitive status. |
| View audit records | No | No by default | No | Restricted operational policy | Clinical-content minimization and purpose restrictions apply. |

## Mandatory checks for protected requests

1. Authentication is valid and the account is active.
2. The primary role permits the operation.
3. The resource exists within the caller's permitted ownership/assignment scope.
4. The consultation, prediction, review, approval, report, or file is in an eligible state/version.
5. Mutations match the expected row/revision version and idempotency scope.
6. Assignment is checked again inside the approval transaction.
7. The event is audited when required, without logging tokens or unrestricted clinical bodies.

## Assignment rules

- A consultation has at most one active assigned doctor in the first release.
- Assignment requires an active verified doctor profile.
- Reassignment is an audited admin operation with a reason.
- The prior doctor loses pending clinical authority immediately after reassignment.
- Reassignment does not alter historical reviewer or approver identity.
- Competing assignment/review/approval changes use the consultation row version and return `409` when stale.
- Admin assignment access does not imply permission to open raw clinical content.

## Decisions requiring clinic approval

- Whether a doctor may create or submit on behalf of a patient.
- Whether a doctor may directly correct model-bound input and under what provenance.
- Whether patients can upload attachments before review.
- Clinical collection/verification authority for Disease, Nadi, and Prakriti; see
  [clinical governance](clinical-governance.md). API existence hiding is defined in
  [the API contract](api-contract.md).
- Operational conditions for inference/report retry.
- Emergency/break-glass access, if any; none is assumed.
