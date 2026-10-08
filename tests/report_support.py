"""Synthetic approvals only, through the existing isolated Phase 6 fixture."""
from backend.app import review
from tests.review_support import seed_case, save, approval_payload, approve


def approved_case(app, monkeypatch, **changes):
    case = seed_case(app)
    draft = save(case, **changes)
    assert draft.status_code == 201
    # Only this isolated fixture mocks the existing policy; never application config.
    with monkeypatch.context() as patch:
        patch.setattr(review, "require_approval_policy", lambda source: {"syntheticTestOnly": True})
        approval = approve(case, approval_payload(draft))
    assert approval.status_code == 201
    case["approval"] = approval.json["data"]["approval"]
    case["report_payload"] = {"approvalId": case["approval"]["id"], "reportVersion": "approved-patient-v1"}
    return case


def generate(case, actor="patient"):
    return case["client"].post(case["url"] + "/reports", json=case["report_payload"], headers=case["headers"][actor])
