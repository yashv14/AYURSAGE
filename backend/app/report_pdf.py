"""PDF template v1: allowlisted immutable patient projection only."""
from io import BytesIO
from xml.sax.saxutils import escape
from threading import Lock
import unicodedata
from pathlib import Path
from hashlib import sha256
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

from .inference import TARGETS
from .storage import MAX_PDF_BYTES

TEMPLATE_VERSION = "approved-patient-v1"
FONT_PATH = os.environ.get("REPORT_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_SHA256 = "57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e"
FONT_LOCK = Lock()
FIELDS = {TARGETS[0]: ("category", "reasoning"),
          TARGETS[1]: ("category", "focus", "actions", "dietary_changes", "wellness_tips", "avoid", "reasoning"),
          TARGETS[2]: ("category", "focus", "duration", "poses", "pranayama", "meditation", "benefits", "precautions", "reasoning"),
          TARGETS[3]: ("category", "reasoning")}
LIST_FIELDS = {"actions", "dietary_changes", "wellness_tips", "avoid", "poses", "pranayama", "benefits", "precautions"}


class RenderError(Exception):
    pass


def projection_sections(content):
    """Strictly exclude restricted data even if extra keys enter a snapshot."""
    required = {"consultationId", "inputRevision", "reviewRevision", "doctorId",
                "recommendations", "careNotes", "prescription"}
    if type(content) is not dict or set(content) != required or set(content["recommendations"]) != set(TARGETS):
        raise RenderError("Invalid patient projection")
    sections = []
    for target in TARGETS:
        value = content["recommendations"][target]
        if type(value) is not dict:
            raise RenderError("Invalid recommendation")
        if set(value) == {"text"}:
            entries = [(None, value["text"])]
        elif set(value) == set(FIELDS[target]):
            entries = []
            for field in FIELDS[target]:
                item = value[field]
                if field in LIST_FIELDS:
                    if type(item) is not list or any(type(text) is not str for text in item):
                        raise RenderError("Invalid recommendation")
                    entries.extend((field.replace("_", " ").capitalize(), text) for text in item)
                else:
                    entries.append((field.replace("_", " ").capitalize(), item))
        else:
            raise RenderError("Invalid recommendation")
        sections.append((target, entries))
    if type(content["careNotes"]) is not str or not content["careNotes"].strip():
        raise RenderError("Incomplete care notes")
    sections.append(("Doctor care notes", [(None, content["careNotes"])]))
    if content["prescription"] is not None:
        sections.append(("Doctor prescription", [(None, content["prescription"])]))
    if any(type(text) is not str or not text.strip() or len(text) > 16000
           for _, entries in sections for _, text in entries):
        raise RenderError("Invalid approved text")
    return sections


def render_pdf(approval_view, report_id, font_path=FONT_PATH, *, synthetic=False):
    sections = projection_sections(approval_view["approvedContent"])
    # Template identity includes the exact font; font drift must not change retry bytes.
    if sha256(Path(font_path).read_bytes()).hexdigest() != FONT_SHA256:
        raise RenderError("Template font integrity failure")
    with FONT_LOCK:
        # Stable font identity per file; renderer has no patient/user-controlled font paths.
        name = "ReportFont-" + sha256(font_path.encode()).hexdigest()[:12]
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, font_path))
        font = pdfmetrics.getFont(name)
    text_values = [text for _, entries in sections for _, text in entries]
    if any(ord(char) not in font.face.charToGlyph for text in text_values for char in text
           if char not in "\n\r\t"):
        raise RenderError("Unsupported character")
    # This template supports LTR Latin/Greek/Cyrillic and covered symbols. Refuse
    # scripts requiring shaping/bidi rather than emitting misleading glyph order.
    for text in text_values:
        for char in text:
            if ((unicodedata.category(char).startswith("L") and not
                 unicodedata.name(char, "").startswith(("LATIN", "GREEK", "CYRILLIC")))
                    or unicodedata.category(char) == "Cf"
                    or (unicodedata.category(char) == "Cc" and char not in "\n\r\t")):
                raise RenderError("Unsupported script")
    if sum(map(len, text_values)) > 160000:
        raise RenderError("Report content exceeds limit")
    normal = ParagraphStyle("body", fontName=name, fontSize=10, leading=15,
                            spaceAfter=7, splitLongWords=True)
    heading = ParagraphStyle("heading", parent=normal, fontSize=12, leading=18,
                             spaceBefore=12, keepWithNext=True, textColor=colors.HexColor("#17483c"))
    title = ParagraphStyle("title", parent=heading, fontSize=18, leading=24)
    def paragraph(text, style=normal):
        return Paragraph(escape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>"), style)
    story = [paragraph("AYUR-SAGE approved report", title)]
    if synthetic:
        story.append(paragraph("SYNTHETIC TEST DATA — NOT FOR CLINICAL USE", heading))
    for label, value in (("Approval ID", approval_view["id"]), ("Approval version", str(approval_view["version"])),
                         ("Approved at (UTC)", approval_view["approvedAt"]), ("Report ID", report_id),
                         ("Template/report version", TEMPLATE_VERSION)):
        story.append(paragraph(f"{label}: {value}"))
    for label, entries in sections:
        story.append(paragraph(label, heading))
        for field, text in entries:
            story.append(paragraph((field + ": " if field else "") + text))
    buffer = BytesIO()
    def page(canvas, document):
        canvas.saveState()
        canvas.setFont(name, 8)
        canvas.drawString(42, 25, "SYNTHETIC TEST DATA" if synthetic else "Approved snapshot report")
        canvas.drawRightString(A4[0] - 42, 25, f"Page {document.page}")
        canvas.restoreState()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42,
                      topMargin=36, bottomMargin=45, title="AYUR-SAGE approved report",
                      author="", invariant=1).build(story, onFirstPage=page, onLaterPages=page)
    data = buffer.getvalue()
    if len(data) > MAX_PDF_BYTES:
        raise RenderError("Report file exceeds limit")
    return data
