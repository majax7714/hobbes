"""The tail view: classify unresolved call sites by observation (ADR-045).

Resolution coverage (ADR-029, C-2) counts how many detected call sites
have no known destination. This module says what the uncounted remainder
*is* — by observation only, never by inference. Every class states a
checkable fact about the site:

- ``fallback-resolved`` — lane A's resolver produced a (syntactic) edge
  for this site; only the semantic provider came up empty.
- ``local-binding`` — the checker resolved the callee to a declaration
  **in the same file**, below the graph's modelled vocabulary (C-9): a
  destructured setter, a handler ``const``, a nested function. Seen and
  deliberately not modelled — not unknown.
- ``nested-decl`` — same, but the declaration lives in another repo file.
- ``external-origin`` — every declaration the checker found lives outside
  the repo: a dependency or an ambient lib. Known origin, unresolved call.
- ``import-binding`` — a bare call whose name an import statement **in
  the same file** binds (``from x import y as z`` binds ``z``). The
  binding is lane A's own parse, not a guess; what stays open is only
  where the imported thing's call would land — often a dependency the
  environment is missing (C-23/C-27/C-30), which is exactly when this
  class carries the tail. Added after the SELENEX/qwen run: their
  ``unclassified`` was almost entirely this (``PG_UUID``,
  ``load_dataset``, ``LLM`` — imports of the very packages
  ``dependency_coverage`` reported missing).
- ``builtin-name`` — a bare call whose name matches the language's pinned
  builtin list. The class says "matches": a local shadowing ``len`` would
  match too, and the name is honest about that. An import binding
  outranks a builtin match — ``from rich import print`` makes the
  import the truer observation about ``print(...)``.
- ``attr-call`` — an attribute call (``x.foo()``): a receiver no static
  provider could type. The genuine static-analysis limit, C-2's core.
- ``path-call`` — a ``::``-qualified call (Rust) the index left dark.
- ``unclassified`` — none of the above observations applies. This is the
  residue that stays honestly unknown.

The classes roll up into the two statements the ingest summary prints
(architecture §3.4): *seen and not modelled by design* (local-binding,
nested-decl, builtin-name) versus *cannot resolve* (everything else but
fallback-resolved, which has an edge and merely lacks proof).

Checker-origin classes are **TypeScript/JavaScript only** in this
version — the tsextract helper's checker knows declarations; the other
syntax providers do not resolve. The asymmetry, the pinned (not
runtime) builtin lists, and the text-based shape read are the
classifier's own boundaries, registered as C-32.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path, PurePosixPath

#: Classes, in the order they are decided. First observation wins.
FALLBACK = "fallback-resolved"
LOCAL = "local-binding"
NESTED = "nested-decl"
EXTERNAL_ORIGIN = "external-origin"
IMPORT_BINDING = "import-binding"
BUILTIN = "builtin-name"
ATTR = "attr-call"
PATH_CALL = "path-call"
UNCLASSIFIED = "unclassified"

#: Rollup: sites the graph sees and deliberately does not model. The
#: complement (minus FALLBACK) is what it cannot resolve — the register's
#: "concentrated need" (ADR-045).
NOT_MODELLED = frozenset({LOCAL, NESTED, BUILTIN})

_LANG_BY_EXT = {
    ".py": "python",
    ".ts": "ts/js",
    ".tsx": "ts/js",
    ".js": "ts/js",
    ".jsx": "ts/js",
    ".mjs": "ts/js",
    ".cjs": "ts/js",
    ".go": "go",
    ".rs": "rust",
}

#: Pinned, not read from the running interpreter (determinism across
#: boxes; the C-3 lift documented what a runtime-bound list costs).
#: Python 3.13 ``builtins``, underscored names dropped.
PY_BUILTINS = frozenset({
    "ArithmeticError", "AssertionError", "AttributeError", "BaseException",
    "BaseExceptionGroup", "BlockingIOError", "BrokenPipeError",
    "BufferError", "BytesWarning", "ChildProcessError",
    "ConnectionAbortedError", "ConnectionError", "ConnectionRefusedError",
    "ConnectionResetError", "DeprecationWarning", "EOFError", "Ellipsis",
    "EncodingWarning", "EnvironmentError", "Exception", "ExceptionGroup",
    "False", "FileExistsError", "FileNotFoundError", "FloatingPointError",
    "FutureWarning", "GeneratorExit", "IOError", "ImportError",
    "ImportWarning", "IndentationError", "IndexError", "InterruptedError",
    "IsADirectoryError", "KeyError", "KeyboardInterrupt", "LookupError",
    "MemoryError", "ModuleNotFoundError", "NameError", "None",
    "NotADirectoryError", "NotImplemented", "NotImplementedError",
    "OSError", "OverflowError", "PendingDeprecationWarning",
    "PermissionError", "ProcessLookupError", "PythonFinalizationError",
    "RecursionError", "ReferenceError", "ResourceWarning", "RuntimeError",
    "RuntimeWarning", "StopAsyncIteration", "StopIteration", "SyntaxError",
    "SyntaxWarning", "SystemError", "SystemExit", "TabError",
    "TimeoutError", "True", "TypeError", "UnboundLocalError",
    "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeError",
    "UnicodeTranslateError", "UnicodeWarning", "UserWarning", "ValueError",
    "Warning", "ZeroDivisionError", "abs", "aiter", "all", "anext", "any",
    "ascii", "bin", "bool", "breakpoint", "bytearray", "bytes", "callable",
    "chr", "classmethod", "compile", "complex", "copyright", "credits",
    "delattr", "dict", "dir", "divmod", "enumerate", "eval", "exec",
    "exit", "filter", "float", "format", "frozenset", "getattr",
    "globals", "hasattr", "hash", "help", "hex", "id", "input", "int",
    "isinstance", "issubclass", "iter", "len", "license", "list",
    "locals", "map", "max", "memoryview", "min", "next", "object", "oct",
    "open", "ord", "pow", "print", "property", "quit", "range", "repr",
    "reversed", "round", "set", "setattr", "slice", "sorted",
    "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
})

#: The Go spec's predeclared functions and convertible predeclared types
#: — both are spelled exactly like calls at a call site (ADR-037).
GO_BUILTINS = frozenset({
    "append", "cap", "clear", "close", "complex", "copy", "delete",
    "imag", "len", "make", "max", "min", "new", "panic", "print",
    "println", "real", "recover",
    "bool", "byte", "complex64", "complex128", "error", "float32",
    "float64", "int", "int8", "int16", "int32", "int64", "rune",
    "string", "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
})

_BUILTINS = {"python": PY_BUILTINS, "go": GO_BUILTINS}

#: Checker origin (tsextract v4) -> tail class.
_ORIGIN_CLASS = {"local": LOCAL, "nested": NESTED, "external": EXTERNAL_ORIGIN}


def language_of(file: str) -> str | None:
    """The tail-view language bucket for *file*, or None (e.g. ``.tf``)."""
    return _LANG_BY_EXT.get(PurePosixPath(file).suffix)


def _shape(line_text: str, name: str, col: int) -> str | None:
    """What immediately precedes *name* on its line: ``attr``, ``path``,
    ``bare`` — or None when the name cannot be located (wrapped chains
    put the terminal on a line the recorded text may not contain)."""
    hits, start = [], 0
    while (found := line_text.find(name, start)) != -1:
        hits.append(found)
        start = found + 1
    if not hits:
        return None
    at = min(hits, key=lambda h: abs(h - col)) if col >= 0 else hits[0]
    j = at - 1
    while j >= 0 and line_text[j] in " \t":
        j -= 1
    if j < 0:
        return "bare"
    if line_text[j] == ":" and j >= 1 and line_text[j - 1] == ":":
        return "path"
    if line_text[j] in ".?!":
        return "attr"
    return "bare"


class _Lines:
    """Source lines per file, read once, repo-root-relative, read-only."""

    def __init__(self, repo_root: Path):
        self.root = Path(repo_root)
        self.cache: dict[str, list[str]] = {}

    def line(self, file: str, number: int) -> str | None:
        if file not in self.cache:
            try:
                text = (self.root / file).read_text(errors="replace")
            except OSError:
                text = ""
            self.cache[file] = text.splitlines()
        lines = self.cache[file]
        return lines[number - 1] if 0 < number <= len(lines) else None


def classify(
    unresolved: list,
    repo_root: Path,
    origins: dict[tuple[str, int, str], str] | None = None,
    fallback: dict[tuple[str, int, str], tuple] | None = None,
    import_bindings: dict[str, frozenset[str]] | None = None,
) -> dict[str, Counter]:
    """Per-file tail classes for the *unresolved* call sites.

    *origins* is the checker's verdict per site (tsextract v4), keyed
    like the fallback dict: ``(file, line, name)``. *import_bindings*
    maps a file to the names its import statements bind (lane A's own
    parse — Python's ``FromImport`` bound names today). Every input
    site lands in exactly one class, so per file the counts sum to the
    coverage row's ``unresolved`` — an invariant the tests pin.
    """
    origins = origins or {}
    fallback = fallback or {}
    import_bindings = import_bindings or {}
    lines = _Lines(repo_root)
    out: dict[str, Counter] = {}
    for site in unresolved:
        key = (site.file, site.line, site.name)
        lang = language_of(site.file)
        if key in fallback:
            cls = FALLBACK
        elif key in origins and origins[key] in _ORIGIN_CLASS:
            cls = _ORIGIN_CLASS[origins[key]]
        else:
            text = lines.line(site.file, site.line)
            shape = _shape(text, site.name, site.col) if text is not None else None
            builtins_ = _BUILTINS.get(lang or "", frozenset())
            bound = import_bindings.get(site.file, frozenset())
            if shape == "bare" and site.name in bound:
                cls = IMPORT_BINDING
            elif shape == "bare" and site.name in builtins_:
                cls = BUILTIN
            elif shape == "attr":
                cls = ATTR
            elif shape == "path":
                cls = PATH_CALL
            else:
                cls = UNCLASSIFIED
        out.setdefault(site.file, Counter())[cls] += 1
    return out


def rollup(coverage_rows: list[dict]) -> dict[str, dict]:
    """Per-language tail totals from ``resolution_coverage`` rows.

    Pure read over the artifact — the CLI summary and any other consumer
    derive the rollup rather than storing it twice.
    """
    langs: dict[str, dict] = {}
    for row in coverage_rows:
        lang = language_of(row["file"])
        if lang is None:
            continue
        agg = langs.setdefault(
            lang, {"sites": 0, "unresolved": 0, "tail": Counter()}
        )
        agg["sites"] += row["sites"]
        agg["unresolved"] += row["unresolved"]
        for cls, count in (row.get("tail") or {}).items():
            agg["tail"][cls] += count
    return langs
