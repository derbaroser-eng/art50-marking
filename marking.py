#!/usr/bin/env python3
"""art50-marking — machine-readable marking of AI-generated outputs.

Stdlib-only implementation snippet from the AI Act Art.50(2) Marking
Readiness Pack. Injects standards-based provenance metadata so synthetic
media is detectable as artificially generated:

  JPEG  -> APP1 XMP packet, IPTC DigitalSourceType = trainedAlgorithmicMedia
  PNG   -> iTXt chunk (XML:com.adobe.xmp), same XMP packet, CRC-correct
  other -> <file>.art50.json sidecar manifest (sha256-bound) + verify mode

Re-marking replaces the previous marking packet; it never duplicates.
This is an implementation aid, NOT legal advice.

CLI:
  python marking.py mark SRC DST      # embed marking (jpg/jpeg/png)
  python marking.py verify FILE       # exit 0 MARKED / exit 1 NOT MARKED
  python marking.py sidecar FILE      # write+verify hash-bound sidecar
  python marking.py xmp               # print the XMP packet
"""
import hashlib
import json
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.0.0"
SOURCE_TYPE = ("http://cv.iptc.org/newscodes/digitalsourcetype/"
               "trainedAlgorithmicMedia")
XMP_NS = b"http://ns.adobe.com/xap/1.0/\x00"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_XMP_KEYWORD = b"XML:com.adobe.xmp"
SIDECAR_SUFFIX = ".art50.json"


def build_xmp(generator="art50-marking/" + __version__):
    """XMP packet carrying the IPTC digital source type for trained AI media."""
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '    xmlns:iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"\n'
        '   xmp:CreatorTool="' + generator + '"\n'
        '   iptc4xmpExt:DigitalSourceType="' + SOURCE_TYPE + '">\n'
        '   <dc:description>\n'
        '    <rdf:Alt>\n'
        '     <rdf:li xml:lang="x-default">Artificially generated or manipulated '
        'content (AI). Machine-readable marking per EU AI Act Art.50(2).</rdf:li>\n'
        '    </rdf:Alt>\n'
        '   </dc:description>\n'
        '  </rdf:Description>\n'
        ' </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>'
    )


# ---------------- JPEG ----------------

def _jpeg_segments(data):
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG (missing SOI)")
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            raise ValueError("corrupt JPEG at byte %d" % i)
        marker = data[i + 1]
        if marker == 0xD9:  # EOI
            yield (marker, b"", i)
            return
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            yield (marker, b"", i)
            i += 2
            continue
        if marker == 0xDA:  # SOS: entropy-coded data follows until EOI
            ln = struct.unpack(">H", data[i + 2:i + 4])[0]
            yield (marker, data[i + 2:i + 2 + ln], i)
            end = data.rfind(b"\xff\xd9")
            if end < 0:
                raise ValueError("JPEG missing EOI")
            yield (0xD9, b"", end)
            return
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        yield (marker, data[i + 4:i + 2 + ln], i)
        i += 2 + ln
    raise ValueError("JPEG missing EOI")


def _is_std_xmp_app1(marker, payload):
    return marker == 0xE1 and payload.startswith(XMP_NS)


def mark_jpeg(data, xmp=None):
    """Replace any standard XMP APP1 with a fresh marking packet after SOI."""
    xmp = xmp or build_xmp()
    payload = XMP_NS + xmp.encode("utf-8")
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("XMP packet too large for one APP1 segment")
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    out = [b"\xff\xd8", app1]
    for marker, body, _pos in _jpeg_segments(data):
        if _is_std_xmp_app1(marker, body):
            continue  # replace, never duplicate
        if marker == 0xD9:
            out.append(b"\xff\xd9")
        elif marker == 0xDA:
            out.append(b"\xff\xda" + body)
        elif body == b"" and (marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01):
            out.append(bytes([0xFF, marker]))
        else:
            out.append(bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body)
    return b"".join(out)


def read_xmp_jpeg(data):
    for marker, body, _pos in _jpeg_segments(data):
        if _is_std_xmp_app1(marker, body):
            return body[len(XMP_NS):].decode("utf-8", errors="replace")
    return None


# ---------------- PNG ----------------

def _png_chunks(data):
    if data[:8] != PNG_SIG:
        raise ValueError("not a PNG (bad signature)")
    i = 8
    while i < len(data):
        ln = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        body = data[i + 8:i + 8 + ln]
        crc = struct.unpack(">I", data[i + 8 + ln:i + 12 + ln])[0]
        if crc != (zlib.crc32(typ + body) & 0xFFFFFFFF):
            raise ValueError("PNG CRC mismatch in %r" % typ)
        yield typ, body
        i += 12 + ln
        if typ == b"IEND":
            return


def _png_chunk(typ, body):
    return (struct.pack(">I", len(body)) + typ + body
            + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF))


def _is_xmp_itxt(typ, body):
    return typ == b"iTXt" and body.startswith(PNG_XMP_KEYWORD + b"\x00")


def mark_png(data, xmp=None):
    """Replace any XMP iTXt with a fresh marking chunk right after IHDR."""
    xmp = xmp or build_xmp()
    body = PNG_XMP_KEYWORD + b"\x00\x00\x00\x00\x00" + xmp.encode("utf-8")
    new_chunk = _png_chunk(b"iTXt", body)
    out = [PNG_SIG]
    inserted = False
    for typ, chunk_body in _png_chunks(data):
        if _is_xmp_itxt(typ, chunk_body):
            continue  # replace, never duplicate
        out.append(_png_chunk(typ, chunk_body))
        if typ == b"IHDR" and not inserted:
            out.append(new_chunk)
            inserted = True
    if not inserted:
        raise ValueError("PNG missing IHDR")
    return b"".join(out)


def read_xmp_png(data):
    for typ, body in _png_chunks(data):
        if _is_xmp_itxt(typ, body):
            # iTXt = keyword\0 + compression_flag + compression_method +
            # language_tag\0 + translated_keyword\0 + text. Our writer emits
            # PNG_XMP_KEYWORD followed by exactly five NULs, then the XMP text.
            # Splitting on fewer than five leaves a stray NUL before <?xpacket,
            # which strict XML parsers reject.
            return body.split(b"\x00", 5)[5].decode("utf-8", errors="replace")
    return None


# ---------------- detection + sidecar ----------------

def is_marked(data):
    """True when embedded XMP carries the trained-algorithmic-media source type."""
    try:
        if data[:2] == b"\xff\xd8":
            xmp = read_xmp_jpeg(data)
        elif data[:8] == PNG_SIG:
            xmp = read_xmp_png(data)
        else:
            return False
    except ValueError:
        return False
    return bool(xmp) and SOURCE_TYPE in xmp


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sidecar_path(path):
    return Path(str(path) + SIDECAR_SUFFIX)


def write_sidecar(path):
    """Hash-bound machine-readable marking manifest for non-image outputs."""
    path = Path(path)
    meta = {
        "schema": "art50-marking-sidecar/1.0",
        "file": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "digital_source_type": SOURCE_TYPE,
        "marking_standard": "EU AI Act Art.50(2) machine-readable marking; "
                            "IPTC DigitalSourceType vocabulary",
        "marked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "art50-marking/" + __version__,
    }
    sc = sidecar_path(path)
    sc.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return sc


def verify_sidecar(path):
    """True only when the sidecar exists, is well-formed, and the hash matches."""
    path = Path(path)
    sc = sidecar_path(path)
    if not sc.exists():
        return False
    try:
        meta = json.loads(sc.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    if meta.get("schema") != "art50-marking-sidecar/1.0":
        return False
    if meta.get("digital_source_type") != SOURCE_TYPE:
        return False
    return meta.get("sha256") == sha256_file(path)


# ---------------- CLI ----------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip())
        return 2
    cmd = argv[0]
    try:
        if cmd == "xmp":
            print(build_xmp())
            return 0
        if cmd == "mark" and len(argv) == 3:
            src, dst = Path(argv[1]), Path(argv[2])
            data = src.read_bytes()
            if data[:2] == b"\xff\xd8":
                out = mark_jpeg(data)
            elif data[:8] == PNG_SIG:
                out = mark_png(data)
            else:
                print("ERROR: mark supports JPEG/PNG; use 'sidecar' for other files",
                      file=sys.stderr)
                return 2
            dst.write_bytes(out)
            print("MARKED %s -> %s (%d bytes)" % (src, dst, len(out)))
            return 0
        if cmd == "verify" and len(argv) == 2:
            p = Path(argv[1])
            data = p.read_bytes()
            if data[:2] == b"\xff\xd8" or data[:8] == PNG_SIG:
                ok = is_marked(data)
                kind = "embedded-xmp"
            else:
                ok = verify_sidecar(p)
                kind = "sidecar"
            print(("MARKED" if ok else "NOT MARKED") + " (%s): %s" % (kind, p))
            return 0 if ok else 1
        if cmd == "sidecar" and len(argv) == 2:
            sc = write_sidecar(Path(argv[1]))
            ok = verify_sidecar(Path(argv[1]))
            print("SIDECAR %s verify=%s" % (sc, ok))
            return 0 if ok else 1
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    print("usage: marking.py mark SRC DST | verify FILE | sidecar FILE | xmp",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
