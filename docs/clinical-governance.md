# Phase 2 clinical provenance and operational gates

These are application design constraints, not clinical rules. V17 and all supplied
engines remain unavailable until the evidence gates in the integration contract pass.

## Clinical field ownership

| Reported concept | Patient input | Assigned doctor responsibility | Model boundary |
|---|---|---|---|
| Disease | Patient may report history or context in a separate provenance layer. | Records or verifies clinical interpretation; patient reports are not a diagnosis. | Exact model field and accepted values require original evidence. |
| Nadi reading | Patient-reported context is explicitly marked unverified. | Records examination provenance and verifies any required reading under an approved clinic protocol. | No conversion, default, or category inference is permitted. |
| Constitution/Prakriti | Self-report remains distinguishable from clinician assessment. | Records assessment source and verification under an approved clinic protocol. | No questionnaire-to-category mapping is invented. |

These concepts are reported architecture names, not finalized schema keys.
Each eventual field records source actor, source kind, collection time, verification
actor/time where applicable, and schema version. Patient reports, doctor assessments,
raw model results, enrichment, and doctor decisions remain separate. The clinic must
approve collection authority and verification requirements before clinical submission
is enabled. A correction creates a new revision and requires fresh processing/review.

## Privileged onboarding and assignment

Public registration creates only a Patient account. Doctor onboarding requires an
authorized admin, independently reviewed qualification evidence, verification actor
and time, and an audit event before activation or assignment. Admin bootstrap uses a
controlled operator procedure rather than a public endpoint; credentials are never
seeded into Git. Bootstrap, recovery, privilege grants, and revocations require a
documented operator owner before implementation is released.

Submission may remain unassigned while processing, but review and approval require
an active verified assigned doctor. Deactivation prevents further clinical actions;
an authorized admin must reassign the case. Assignment history records prior/new
doctor, actor, reason, and time without changing historical reviewer identities.

## Retention and amendments

No retention duration or legal basis is assumed. Before persistence is released,
the responsible clinic must approve a policy covering input revisions, outputs,
enrichment, reviews, approvals, reports, attachments, audit records, sessions, and
backups, including deletion authority, holds, anonymization, and backup expiry.
Until that policy exists, destructive clinical deletion and automated expiry are
disabled. Account deactivation does not cascade-delete clinical records.

Approved consultations remain immutable. The initial workflow does not enable
amendments; a later reviewed design must explicitly link the new consultation or
approval to the superseded version and define patient-visible report supersession.
Historical snapshots and author identities remain preserved.

## Contraindication and enrichment policy

No contraindication list, severity threshold, or clinical conflict resolver is
defined here. Supplied engine source, context requirements, output semantics, and
authorized reference cases must establish actual behavior. The clinic must approve
which engines are required and how contraindications/conflicts reach doctor review.
Unknown required context or failed required enrichment blocks reviewability and
approval; the application must not interpret absence of a warning as clearance.
Doctor decisions and reasons are recorded separately and cannot rewrite engine output.

## Phase 2 completion evidence

ER, workflow, API, and authorization documents exist on main. This document closes
the independent provenance and operational-policy design gaps. Exact V17 schemas,
dependencies, trusted checksum, parity cases, engine semantics, clinic policy approval,
and legal retention decisions remain explicit blockers. Phase 2 is not fully complete
and Phase 5 inference cannot be enabled from application-design documentation alone.
