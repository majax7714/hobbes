"""Pack: Express and Nest routes (ADR-035, ported from ADR-021).

**Detection stays in the Node helper, and this is the one pack where that
is true.** Express's receiver check (`expressReceiverOk` in
``tsextract/extract.mjs``) asks ts-morph what `app` was initialised to, so
that `app.get("/x", h)` is a route and `cache.get("/x")` is not. Moving that
into Python would mean re-implementing a type question against an AST Python
cannot see, and the honest answer is that the check would get worse.

So the helper *produces* the rows and this pack *claims* them: the pack is
the only path by which Express/Nest routes reach ``interfaces.json``, it
declares their tier, and removing it removes exactly those rows. That is the
whole of the pack contract — the contract is about ownership of a
contribution, not about where the regex lives.
"""

from __future__ import annotations

from hobbes.extract.packs.base import Pack, PackContext, PackResult
from hobbes.extract.schema import SYNTACTIC


def _applies(ctx: PackContext) -> bool:
    """True when the TS layer ran and reported any route rows.

    Unlike the Python HTTP pack this cannot key on an import: the helper has
    already made the framework judgement by the time Python sees anything,
    and re-deriving it here from ``package.json`` would be a second opinion
    that can disagree with the first (P1).
    """
    return bool(ctx.ts and ctx.ts.get("routes"))


def _run(ctx: PackContext) -> PackResult:
    return PackResult(routes=list(ctx.ts["routes"]))


PACK = Pack(name="http-ts", tier=SYNTACTIC, applies=_applies, run=_run)
