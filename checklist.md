# Art. 50(2) Marking Self-Audit Checklist

Scope: providers and deployers of generative AI systems placing synthetic
audio, image, video or text outputs on the EU market. Maps the machine-readable
marking duty of Art. 50(2) of Regulation (EU) 2024/1689 (AI Act) to concrete
engineering checks you can run today with `marking.py`.

**Deadline.** Art. 50 has applied since 2 August 2026. Systems placed on the
market before that date have a transitional period until **2026-12-02** to meet
the Art. 50(2) machine-readable marking duty (Art. 111(4), as amended by
Regulation (EU) 2026/1744, the Digital Omnibus on AI). Systems placed on the
market on or after 2 August 2026 have no grace period.

**This checklist is an engineering aid, not legal advice.** No lawyer-client
relationship; not a conformity certificate.

## 1. Effective - the marking is present on every output

- [ ] Every synthetic JPEG/PNG is marked at generation time:
      `python marking.py mark SRC DST` (exit 0).
- [ ] Every other synthetic output (text/audio/video) has a hash-bound
      sidecar: `python marking.py sidecar FILE` (writes `<file>.art50.json`).
- [ ] Spot-check finished outputs: `python marking.py verify FILE`
      (exit 0 = MARKED, exit 1 = NOT MARKED). Unmarked output must not ship.

## 2. Interoperable - standards-based, third-party detectable

- [ ] JPEG: APP1 XMP packet with IPTC DigitalSourceType =
      `trainedAlgorithmicMedia`, readable by any XMP-aware tool.
- [ ] PNG: `iTXt` chunk keyed `XML:com.adobe.xmp`, CRC-correct, after IHDR.
- [ ] Other formats: same IPTC source type + file sha256 in a JSON sidecar.
- [ ] No proprietary-only format is the sole marking channel.

## 3. Robust - survives normal handling

- [ ] Re-marking replaces, never duplicates (idempotent; acceptance-tested).
- [ ] After transcode/resize/re-encode, re-run `verify`; re-apply if stripped.
- [ ] Tamper check: edit a sidecar-marked file by one byte; `verify` must fail.

## 4. Reliable - reproducible and auditable

- [ ] Marking runs inside the generation pipeline, not by hand.
- [ ] Sidecars record UTC timestamp + generator version.
- [ ] Keep verify logs (command, file, exit code, date) as evidence.
- [ ] Re-run the suite after pipeline changes:
      `python -m unittest test_art50 -v` (14 tests, exit 0).

## 5. Deployer text notice (Art. 50(4))

- [ ] Fill `disclosure-template.md`; show it to natural persons exposed to
      the output, in addition to the machine-readable mark.

## Evidence to retain

1. Marked output (or output + its `.art50.json` sidecar).
2. `verify` exit-code log for a sample of outputs per release.
3. The filled disclosure template actually shown to users.
4. This checklist, dated and signed off by the responsible engineer.

Sources: Regulation (EU) 2024/1689 Art. 50; Regulation (EU) 2026/1744
(Art. 111(4) transition); IPTC DigitalSourceType newscode vocabulary.
