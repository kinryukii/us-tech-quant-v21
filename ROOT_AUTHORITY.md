# Root authority files

A small set of Python implementations and tests must currently remain in the
repository root because existing contracts bind their exact paths or content.
Those contracts include frozen SHA identities, reviewed/source/economic
manifests, the research registry, Harness loading, and active prospective
registrations. The root FAST3 launchers are likewise protected compatibility
entrypoints.

Their conceptual homes remain:

- `scripts/research/a2/data`, `scripts/research/a2/risk`, and
  `scripts/research/a2/portfolio` for A2 research implementations;
- `scripts/maintenance` for registry, lifecycle, and maintenance code;
- `tests/research/a2` and `tests/governance` for the corresponding tests.

Physical moves are deferred until a separately authorized migration can update
the whole frozen/provenance chain without weakening path, hash, Harness,
registry, prospective, or compatibility guarantees. VS Code may visually nest
these root files under this document, and the FAST3 launchers under `FAST3.md`,
without changing their filesystem locations.

This document is informational only. It is not an authoritative manifest or a
replacement for the existing frozen contracts, manifests, or registry.
