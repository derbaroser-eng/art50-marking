# art50-marking - AI Act Art.50(2) Marking Readiness Pack

Machine-readable marking of AI-generated outputs ahead of the Art. 50(2)
transition deadline (**2026-12-02** for systems placed on the market before
2 August 2026; Art. 111(4) as amended by Regulation (EU) 2026/1744).

**EUR 29 one-time** - offer: https://derbaroser-eng.github.io/art50-marking/

## Pack contents

1. `marking.py` - stdlib-only Python: JPEG APP1 XMP / PNG iTXt marking with
   IPTC DigitalSourceType `trainedAlgorithmicMedia`; sha256-bound
   `<file>.art50.json` sidecars for other formats; idempotent re-marking.
2. `checklist.md` - self-audit checklist mapped to Art. 50(2) obligations.
3. `disclosure-template.md` - deployer disclosure template (Art. 50(4)).

## Run

    python marking.py mark SRC DST   # embed marking (jpg/jpeg/png)
    python marking.py verify FILE    # exit 0 MARKED / exit 1 NOT MARKED
    python marking.py sidecar FILE   # write + verify hash-bound sidecar
    python marking.py xmp            # print the XMP packet

## Test

    python -m unittest test_art50 -v   # 14 acceptance tests, exit 0

Includes negative cases: unmarked files fail verify, tampered sidecars fail,
re-marking never duplicates packets.

## License

MIT (LICENSE). The snippet is free to embed; the pack sells the bundle,
checklist and template.

Engineering aid, **not legal advice**. Not a conformity certificate.
Built with AI assistance.
