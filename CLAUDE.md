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
- `--use-mutablestruct`: translate classes to `larky.mutablestruct` instead of the default desugaring.
- `--use-error-not-fail`: rewrite `raise` to the `Error` module instead of `fail()`.

## Architecture

`pipeline.larkify()` (called by `cli.py`) runs everything:

1. `cli.safe_read` detects the encoding and re-indents with `utils.ReIndenter` (tabs to spaces).
2. `pipeline.transform_passes()` returns the ordered list of `ContextAwareTransformer`s in `py2star/asteez/`. Order matters:
   - Desugaring first (`desugar.py`: string concat, byte prefixes, decorators, `**`, set literals, multi-target assignment, `del`), then `while` to bounded `for`, type checks, generators, chained/`is` comparisons, annotation removal, `RemoveExceptions`.
   - The class rewriter runs last because it restructures the module: `rewrite_class.ClassToFunctionRewriter` normally, or `rewrite_tests.UnittestAssertMethodsRewriter` + `Unittest2Functions` in `-t` mode.
   - Config reaches transformers through `context.scratch["config"]`.
3. `pipeline.import_passes()` runs on a fresh `MetadataWrapper`: `AddImportsVisitor` / `RemoveImportsVisitor` apply imports queued by earlier passes (`AddImportsVisitor.add_needed_import`), `RewriteImports` turns `import`s into `load()`, and `LarkyImportSorter` hoists and sorts the loads.

A new transformer does nothing until it is added to `transform_passes()` in the right position. `rewrite_fstring.RemoveFStrings` exists but is not in the pipeline.

Other modules: `larky.py` is a shim that lets `.star` files run under CPython; `tokenizers/` backs the `defs` command.

## Tests

Most coverage is in `tests/test_asteez.py`, using `libcst.codemod.CodemodTest`: each class sets `TRANSFORM = SomeTransformer` and calls `self.assertCodemod(before, after)` with dedented strings. Transformers with `METADATA_DEPENDENCIES` subclass `MetadataResolvingCodemodTest`. These tests exercise one transformer at a time, not the full pipeline, so check pipeline-level changes by running `py2star larkify` on the files in `tests/data/` before and after.
