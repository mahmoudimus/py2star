# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`py2star` converts Python source into Starlark for [Larky](https://github.com/verygoodsecurity/starlarky) (VGS's Starlark dialect). Output uses Larky conventions: `load("@stdlib//...")` / `load("@vendor//...")`, `larky.mutablestruct`, `operator.*`, `sets.make()`, `Result`/`Error`. The output is a starting point for a manual port, not a finished one. `MIGRATING.md` holds hand-port patterns (no recursion, no try/except, operator overloading via `operator.star`). `ROADMAP.md` lists known gaps.

All transformations are libcst passes. There is no lib2to3 or stdlib-`ast` rewriting; keep it that way.

## Environment

- Python 3.10+ (`sys.stdlib_module_names` decides `@stdlib` vs `@vendor`). Tested on 3.10, 3.12, 3.13, 3.14.
- The only runtime dependency is `libcst` (pinned in `requirements.txt`).

```bash
pip install -e '.[tests]'
```

## Commands

```bash
pytest                                              # all tests (config in setup.cfg)
pytest tests/test_asteez.py::TestDesugarSetSyntax   # one class
pytest tests/test_asteez.py -k unpack_nested        # one test

py2star larkify path/to/file.py > out.star
py2star larkify -t path/to/test_x.py > test_x.star  # unittest -> Larky test mode, appends a suite runner
py2star -p jose larkify jose/jwt.py                 # -p goes before the subcommand
py2star tests out.star                              # print a suite runner for an existing file
py2star defs file.py                                # list function definitions
```

`larkify` flags:
- `-p/--pkg-path`: package root. Without it, relative imports become `@vendor///name` with a warning on stderr.
- `--use-mutablestruct`: translate classes to `larky.mutablestruct` instead of `types.new_class`. Needed for `@property`.
- `--use-error-not-fail`: `raise` becomes `return Error(...)` instead of `fail(...)`. Raises inside a `try` body always raise.
- `--unwrap-errors`: `raise` becomes `return Error(...).unwrap()`.

Larky end-to-end tests (`tests/e2e/*.py` run under CPython and, larkified, under Larky; outputs compared) are skipped unless `LARKY_JAR` is set:

```bash
LARKY_JAR=~/src/starlarky/larky/target/larky-1.0.0-SNAPSHOT-jar-with-dependencies.jar pytest tests/test_larky_e2e.py
```

CI (`.github/workflows/tests.yml`) runs the unit tests on Python 3.10-3.14 and the Larky tests against starlarky built from source at a pinned commit of the `mahmoudimus/starlarky` fork (`STARLARKY_REPO`/`STARLARKY_REF`; the fork has the `format()` built-in, and the release binaries cannot load `@stdlib//larky`). The fork's jar needs Java 21. It sets `REQUIRE_LARKY=1`, which turns the skip into a failure. `test-requirements.txt` is only what the tests need; personal debugging tools live in `dev-requirements.txt`.

Use them to check what Larky actually accepts before relying on it: many Python builtins and syntax are missing, and some stdlib helpers have bugs (e.g. `operator.delitem` always fails for dicts). `tests/larky/RunStar.java` is the launcher; `Larky.main` itself cannot run files that use `load()`.

## Architecture

`pipeline.larkify()` (called by `cli.py`) runs everything:

1. `cli.safe_read` detects the encoding and re-indents with `utils.ReIndenter` (tabs to spaces).
2. `pipeline.transform_passes()` returns the ordered list of `ContextAwareTransformer`s in `py2star/asteez/`. Order matters:
   - Desugaring first (`desugar.py`: string concat, f-strings, byte prefixes, `str.encode`, decorators, `**`, sets, missing builtins, `del`, slice assignment), then `nonlocal`/`global` (`rewrite_scopes.py`), `while`, type checks, generators, comparisons, annotation removal.
   - `RemoveExceptions` turns `raise` into `fail`/`Error`, then `TryExceptToResult` turns `try` into `Result` calls; it relies on raises in try bodies already raising. `ForElseToFlag` runs after it because try bodies' `break`s move out.
   - The class rewriter runs last because it restructures the module: `rewrite_class.ClassToFunctionRewriter` normally, or `rewrite_tests.UnittestAssertMethodsRewriter` + `Unittest2Functions` in `-t` mode. It must ignore functions nested inside methods (including generated `_try_N` helpers).
   - Config reaches transformers through `context.scratch["config"]`.
3. `pipeline.import_passes()` runs on a fresh `MetadataWrapper`: `AddImportsVisitor` / `RemoveImportsVisitor` apply imports queued by earlier passes (`AddImportsVisitor.add_needed_import`), `RewriteImports` turns `import`s into `load()`, and `LarkyImportSorter` hoists and sorts the loads.

String formatting (f-strings, `str.format()` specs, printf `%`) is translated in `rewrite_fstring.py` to `"...{}...".format(...)` with plain `{}` fields, passing spec'd values through `format(value, spec)` and `%r`/`!r` through `repr()`. Never emit `%` formatting or `str.format()` specs: hosts can inject a Python-compatible `format()`, but not always change Starlark's `%` or `str.format()`. The output also runs unchanged in CPython. `tests/test_features.py` checks both properties.

A new transformer does nothing until it is added to `transform_passes()` in the right position. Generated helper names use a leading underscore and a per-module counter (`_try_1`, `_broke_1`, `_lo_s1`); constructs that cannot be translated keep their code and get a `# PY2LARKY:` comment.

Other modules: `larky.py` is a shim that lets `.star` files run under CPython; `tokenizers/` backs the `defs` command.

## Tests

Most coverage is in `tests/test_asteez.py`, using `libcst.codemod.CodemodTest`: each class sets `TRANSFORM = SomeTransformer` and calls `self.assertCodemod(before, after)` with dedented strings. Transformers with `METADATA_DEPENDENCIES` subclass `MetadataResolvingCodemodTest`. `tests/test_features.py` pins before/after output for the feature passes. These tests exercise one transformer at a time; for pipeline-level changes, also diff `py2star larkify` output on the files in `tests/data/` before and after, and run the Larky end-to-end tests.
