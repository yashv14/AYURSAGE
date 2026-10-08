"""Template font integrity is enforced independently of distro package identity."""
import pytest

from scripts.prepare_report_font import prepare, verified, FONT_SHA256
from backend.app.report_pdf import render_pdf, RenderError
from scripts.sample_report_pdfs import samples


def test_font_checksum_mismatch_is_rejected_before_publication(tmp_path):
    font = tmp_path / "DejaVuSans.ttf"
    font.write_bytes(b"wrong-font")
    with pytest.raises(ValueError, match="checksum"):
        prepare(font)
    assert font.read_bytes() == b"wrong-font"
    with pytest.raises(ValueError, match="checksum"):
        verified(b"wrong-package", FONT_SHA256)
    with pytest.raises(RenderError, match="font integrity"):
        render_pdf(samples()["short-no-prescription"], "synthetic", font_path=str(font), synthetic=True)


def test_font_destination_symlink_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"preserved")
    link = tmp_path / "DejaVuSans.ttf"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        prepare(link)
    assert target.read_bytes() == b"preserved"
