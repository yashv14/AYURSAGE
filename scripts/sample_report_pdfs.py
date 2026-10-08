"""Generate marked synthetic template samples only; no DB, storage or model access.

Run: python -m scripts.sample_report_pdfs --output /tmp/ayursage-phase7-review
Generated PDFs must never be committed. This is not clinical acceptance evidence.
"""
import argparse
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re

from pypdf import PdfReader

from backend.app.inference import TARGETS
from backend.app.report_pdf import render_pdf, projection_sections


def samples():
    recommendations = {
        TARGETS[0]: {"category": "Synthetic approved category", "reasoning": "Synthetic approved annotation; no clinical advice."},
        TARGETS[1]: {"category": "Synthetic lifestyle category", "focus": "Synthetic approved focus",
                    "actions": ["Synthetic approved action."], "dietary_changes": [],
                    "wellness_tips": ["Synthetic approved tip."], "avoid": [],
                    "reasoning": "Synthetic doctor-approved annotation."},
        TARGETS[2]: {"text": "Synthetic doctor replacement <b>literal markup</b> & café — Ελληνικά — Кириллица."},
        TARGETS[3]: {"text": "Synthetic approved follow-up replacement; no clinical claim."}}
    view = {"id": "00000000-0000-0000-0000-000000000001", "version": 1,
            "approvedAt": "2026-10-08T00:00:00+00:00",
            "approvedContent": {"consultationId": "00000000-0000-0000-0000-000000000002",
                "inputRevision": 1, "reviewRevision": 1,
                "doctorId": "00000000-0000-0000-0000-000000000003",
                "recommendations": recommendations, "careNotes": "Synthetic doctor care notes <script>literal</script> & accented café.",
                "prescription": None}}
    long = deepcopy(view)
    long["approvedContent"]["careNotes"] = "\n".join(
        f"Synthetic approved line {index:03d}: café Ω Ж & literal <tag>; test data only." for index in range(1, 111))
    long["approvedContent"]["prescription"] = "Synthetic optional doctor prescription — no real medication or credentials."
    long["approvedContent"]["recommendations"][TARGETS[0]] = {"text": "Synthetic long token: " + "x" * 300}
    return {"short-no-prescription": view, "long-with-prescription": long}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    repository = Path(__file__).resolve().parents[1]
    if output == repository or repository in output.parents:
        raise SystemExit("Choose an output directory outside the checkout")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = {}
    for name, view in samples().items():
        data = render_pdf(view, "00000000-0000-0000-0000-000000000004", synthetic=True)
        path = output / f"{name}.pdf"
        path.write_bytes(data)
        reader = PdfReader(BytesIO(data))
        text = "\n".join(page.extract_text() for page in reader.pages)
        # Remove layout whitespace only; every projection text value must survive.
        body_text = "\n".join(re.sub(r"\ASYNTHETIC TEST DATA\nPage \d+\n", "", page.extract_text())
                              for page in reader.pages)
        compact = re.sub(r"\s", "", body_text)
        for _, entries in projection_sections(view["approvedContent"]):
            for _, value in entries:
                assert re.sub(r"\s", "", value) in compact, "Approved text missing from sample PDF"
        assert all("SYNTHETIC TEST DATA" in page.extract_text() for page in reader.pages)
        assert view["id"] in text and view["approvedAt"] in text
        (output / f"{name}.txt").write_text(text)
        manifest[name] = {"pages": len(reader.pages), "projectionTextVerified": True, "synthetic": True}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
