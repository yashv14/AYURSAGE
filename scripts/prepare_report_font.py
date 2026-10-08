"""Retrieve the canonical template font without trusting distro-specific font bytes.

No package installation or maintainer scripts. HTTPS, package and font SHA-256
verification precede publication. Existing files are preserved unless already exact.
"""
import argparse
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen

PACKAGE_URL = "https://deb.debian.org/debian/pool/main/f/fonts-dejavu/fonts-dejavu-core_2.37-8_all.deb"
PACKAGE_SHA256 = "86635b3d25b3655fc11cb3ecc3af59f0bf19643b02b94f2de48bd10253cdba12"
FONT_SHA256 = "57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e"
FONT_MEMBER = "usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def verified(data, expected):
    if sha256(data).hexdigest() != expected:
        raise ValueError("Report font artifact checksum mismatch")
    return data


def prepare(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        if output.is_symlink():
            raise ValueError("Report font destination must not be a symlink")
        verified(output.read_bytes(), FONT_SHA256)
        return output
    with tempfile.TemporaryDirectory(prefix="ayursage-font-") as temporary:
        root = Path(temporary)
        with urlopen(PACKAGE_URL, timeout=30) as response:
            if not response.geturl().startswith("https://"):
                raise ValueError("Report font download must remain HTTPS")
            data = response.read(4 * 1024 * 1024 + 1)
        verified(data, PACKAGE_SHA256)
        archive = root / "font.deb"
        archive.write_bytes(data)
        extracted = root / "extracted"
        subprocess.run(["dpkg-deb", "--extract", str(archive), str(extracted)], check=True)
        font = verified((extracted / FONT_MEMBER).read_bytes(), FONT_SHA256)
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary_font = tempfile.mkstemp(prefix=".font-", dir=output.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(font)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_font, output)
            except FileExistsError:
                if output.is_symlink():
                    raise ValueError("Report font destination must not be a symlink")
                verified(output.read_bytes(), FONT_SHA256)
        finally:
            os.unlink(temporary_font)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    print(prepare(parser.parse_args().output))


if __name__ == "__main__":
    main()
