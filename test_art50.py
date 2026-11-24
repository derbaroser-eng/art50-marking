"""Acceptance tests for the Art.50(2) Marking Readiness Pack.

RED first: engine, pack files, landing page and checkout record must all exist
and behave. Every gate is red-able: fixtures include unmarked and tampered cases.
"""
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_TYPE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
XMP_NS = b"http://ns.adobe.com/xap/1.0/\x00"
STRIPE_RE = re.compile(r"https://buy\.stripe\.com/[A-Za-z0-9_-]+")


def jpeg_fixture():
    """Minimal structurally valid JPEG: SOI + APP0/JFIF + EOI."""
    app0_payload = b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00"
    app0 = b"\xff\xe0" + struct.pack(">H", len(app0_payload) + 2) + app0_payload
    return b"\xff\xd8" + app0 + b"\xff\xd9"


def png_chunk(typ, data):
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def png_fixture():
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return sig + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", raw) + png_chunk(b"IEND", b"")


def walk_jpeg(data):
    """Yield (marker, payload) for every segment; raise on structural damage."""
    assert data[:2] == b"\xff\xd8", "missing SOI"
    assert data[-2:] == b"\xff\xd9", "missing EOI"
    i = 2
    while i < len(data) - 2:
        assert data[i] == 0xFF, "bad segment marker at %d" % i
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            i += 2
            continue
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        yield marker, data[i + 4:i + 2 + ln]
        i += 2 + ln
    assert i == len(data) - 2, "segment walk overran EOI"


def walk_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "bad PNG signature"
    i = 8
    while i < len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + ln]
        crc = struct.unpack(">I", data[i + 8 + ln:i + 12 + ln])[0]
        assert crc == (zlib.crc32(typ + body) & 0xFFFFFFFF), "CRC fail: %r" % typ
        yield typ, body
        i += 12 + ln
        if typ == b"IEND":
            break
    assert i == len(data), "trailing garbage after IEND"


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        import marking
        cls.m = marking

    def test_01_xmp_carries_iptc_source_type(self):
        xmp = self.m.build_xmp()
        self.assertIn(SOURCE_TYPE, xmp)
        self.assertIn("DigitalSourceType", xmp)
        self.assertIn("<x:xmpmeta", xmp)

    def test_02_jpeg_marked_structurally_valid(self):
        out = self.m.mark_jpeg(jpeg_fixture())
        segs = list(walk_jpeg(out))  # raises if damaged
        app1 = [p for mk, p in segs if mk == 0xE1 and p.startswith(XMP_NS)]
        self.assertEqual(len(app1), 1, "exactly one standard XMP APP1")
        self.assertIn(SOURCE_TYPE.encode(), app1[0])
        self.assertTrue(any(mk == 0xE0 for mk, _ in segs), "original APP0 lost")

    def test_03_jpeg_remark_replaces_not_duplicates(self):
        once = self.m.mark_jpeg(jpeg_fixture())
        twice = self.m.mark_jpeg(once)
        segs = list(walk_jpeg(twice))
        app1 = [p for mk, p in segs if mk == 0xE1 and p.startswith(XMP_NS)]
        self.assertEqual(len(app1), 1)

    def test_04_png_marked_crc_correct(self):
        out = self.m.mark_png(png_fixture())
        chunks = list(walk_png(out))  # raises on any CRC error
        itxt = [b for t, b in chunks if t == b"iTXt"]
        self.assertEqual(len(itxt), 1)
        self.assertTrue(itxt[0].startswith(b"XML:com.adobe.xmp\x00"))
        self.assertIn(SOURCE_TYPE.encode(), itxt[0])
        self.assertEqual(chunks[0][0], b"IHDR", "iTXt must come after IHDR")

    def test_05_png_remark_replaces_not_duplicates(self):
        once = self.m.mark_png(png_fixture())
        twice = self.m.mark_png(once)
        chunks = list(walk_png(twice))
        self.assertEqual(sum(1 for t, _ in chunks if t == b"iTXt"), 1)

    def test_06_readback_detects_marking(self):
        self.assertTrue(self.m.is_marked(self.m.mark_jpeg(jpeg_fixture())))
        self.assertTrue(self.m.is_marked(self.m.mark_png(png_fixture())))
        self.assertFalse(self.m.is_marked(jpeg_fixture()), "unmarked JPEG read as marked")
        self.assertFalse(self.m.is_marked(png_fixture()), "unmarked PNG read as marked")
        self.assertFalse(self.m.is_marked(b"plain text, not an image"))

    def test_15_png_xmp_readback_is_byte_exact(self):
        """A strict XML consumer must receive the exact packet, no stray NUL."""
        xmp = self.m.build_xmp()
        marked = self.m.mark_png(png_fixture(), xmp=xmp)
        readback = self.m.read_xmp_png(marked)
        self.assertEqual(readback, xmp, "readback corrupted (leading NUL byte)")
        self.assertFalse(readback.startswith("\x00"), "NUL before <?xpacket")

    def test_07_sidecar_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "synthetic.txt"
            f.write_text("AI-generated output", encoding="utf-8")
            sc = self.m.write_sidecar(f)
            self.assertTrue(sc.exists())
            meta = json.loads(sc.read_text(encoding="utf-8"))
            self.assertEqual(meta["sha256"], self.m.sha256_file(f))
            self.assertIn("art50", json.dumps(meta).lower())
            self.assertTrue(self.m.verify_sidecar(f))
            f.write_text("AI-generated output!", encoding="utf-8")  # tamper
            self.assertFalse(self.m.verify_sidecar(f), "tampered file passed sidecar")

    def test_08_cli_mark_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.jpg"
            dst = Path(tmp) / "out.jpg"
            src.write_bytes(jpeg_fixture())
            r = subprocess.run([sys.executable, str(ROOT / "marking.py"),
                                "mark", str(src), str(dst)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(dst.exists())
            v = subprocess.run([sys.executable, str(ROOT / "marking.py"),
                                "verify", str(dst)], capture_output=True, text=True)
            self.assertEqual(v.returncode, 0, v.stderr)
            self.assertIn("MARKED", v.stdout)

    def test_09_cli_verify_unmarked_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "plain.jpg"
            src.write_bytes(jpeg_fixture())
            v = subprocess.run([sys.executable, str(ROOT / "marking.py"),
                                "verify", str(src)], capture_output=True, text=True)
            self.assertEqual(v.returncode, 1, "unmarked file must fail verify")


class PackTests(unittest.TestCase):
    def test_10_checklist_exists_and_maps_obligations(self):
        p = ROOT / "checklist.md"
        self.assertTrue(p.exists(), "checklist.md missing")
        t = p.read_text(encoding="utf-8").lower()
        for token in ("art. 50", "machine-readable", "2026-12-02", "not legal advice"):
            self.assertIn(token, t, "checklist missing: " + token)

    def test_11_disclosure_template_exists(self):
        p = ROOT / "disclosure-template.md"
        self.assertTrue(p.exists(), "disclosure-template.md missing")
        t = p.read_text(encoding="utf-8")
        self.assertIn("[PROVIDER NAME]", t)
        self.assertIn("artificially generated", t.lower())

    def test_12_landing_price_is_payable(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        rec = json.loads((ROOT / "checkout.json").read_text(encoding="utf-8"))
        url = rec["url"]
        self.assertTrue(url.startswith("https://buy.stripe.com/"), url)
        self.assertIn("29", page)
        self.assertIn(url, page, "price has no live checkout behind it")
        self.assertEqual(set(STRIPE_RE.findall(page)), {url},
                         "page carries a checkout not in the API record")
        self.assertNotRegex(page, r"__[A-Z]+__", "unfilled template token")
        self.assertNotIn("amp;mdash", page, "double-escaped entity")

    def test_13_thanks_page_serves_the_pack(self):
        page = (ROOT / "thanks.html").read_text(encoding="utf-8")
        for f in ("checklist.md", "disclosure-template.md", "marking.py"):
            self.assertIn(f, page, "thanks page does not serve " + f)
        self.assertNotRegex(page, r"__[A-Z]+__")

    def test_14_every_absolute_link_resolves(self):
        """A published page must not send a buyer to a 404 (footer cross-link)."""
        import urllib.error
        import urllib.request
        hrefs = set()
        for name in ("index.html", "thanks.html"):
            page = (ROOT / name).read_text(encoding="utf-8")
            hrefs.update(re.findall(r'href="(https://[^"]+)"', page))
        self.assertTrue(hrefs, "no absolute links found to check")
        for url in sorted(hrefs):
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (acceptance-gate)"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    code = resp.status
            except urllib.error.HTTPError as e:
                code = e.code
            self.assertEqual(code, 200, "dead link on published page: " + url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
