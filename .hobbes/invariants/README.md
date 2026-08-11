# invariants/

Confirmed invariants for the Hobbes repo itself — one YAML record per
file, `<id>-<slug>.yaml`, following the schema in architecture §10 as
made precise by **ADR-024**: `id`, `statement` (the prose a human
reads), `scope`, `status`, `compile` (`target` plus, for the three
structured kinds, a machine-readable `rule`), and `guarded_by`.

Records enter as `status: inferred` from the M5 narrative pass, land in
`.hobbes/derived/docs/invariants.inferred.yaml`, and reach this
directory only when a human promotes them — that promotion is a
physical act, not a status flag (ADR-019). `retired` records stay here
as history rather than being deleted.

Only `confirmed` records compile (`hobbes invariants compile`) and
receive review verdicts (`hobbes review`).
