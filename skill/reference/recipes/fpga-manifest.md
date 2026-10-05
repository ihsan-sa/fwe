# fpga-manifest

`fpga_manifest.py` writes `firmware/fwe-manifest.json` with schema
`fwe-fpga-manifest/1` (`reference/fpga.md`), and `--check` says whether the
one on disk is stale. Run it after a sim and a build so `verified` reflects
them. /npie's own driver for this schema is /npie's work in its repo; do not
edit it from here.
