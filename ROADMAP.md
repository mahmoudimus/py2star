# Roadmap

What py2star still gets wrong or leaves untranslated, checked against
starlarky `master` (`045014db`). Each open item fails today, either in
py2star's output or when that output runs in Larky.

## Open bugs

Wrong output from py2star:

- [ ] Slice assignment and slice deletion (`elem[:] = other`, `del x[i:j]`)
  are rewritten as in-place list operations, which assumes a list: an object
  with its own `__setitem__`/`__delitem__` gets list operations instead, and
  stepped slices (`x[::2] = ...`) aren't translated. Waiting on a `slice`
  built-in in starlarky, so py2star can emit
  `operator.setitem(x, slice(i, j), v)`.

- [ ] A class defined inside a class is never attached to it: the nested
  class becomes a local (`Inner = _class_Inner()`, or `def Inner()` with
  `--use-mutablestruct`) that is left out of `__ns` / never set on `self`,
  so `self.Inner` and `Outer.Inner` don't resolve.

## Python that py2star leaves as is, and Larky rejects

- [ ] `with ... as ...` statements.
- [ ] Classes derived from built-in exceptions (`class ParseError(SyntaxError)`):
  Larky has no `SyntaxError` class. One option is a function returning
  `Error("ParseError: ...")`.
- [ ] `type(x).__name__`: in Larky, `type(x)` is a string such as `"string"`,
  so `type(x)` alone is the equivalent.
- [ ] `int(b"101", 2)`: Larky's `int` takes a base only for strings
  (`int("101", 2)` works).
- [ ] An attribute named `load` (`x.load()`): `load` is a Starlark keyword,
  so this doesn't parse.
- [ ] `global`: removed and flagged with a `# PY2LARKY:` comment, because
  module globals are frozen once a Starlark module has loaded.
- [ ] `%`-format precision on integer conversions (`"%.3d" % n`), `%c`, and
  `%` with a format string that isn't a literal: left as `%`.
- [ ] `round`, `oct`: not rewritten.

## Design questions

- `from Crypto.PublicKey import RSA` becomes
  `load("@vendor//Crypto/PublicKey", RSA="RSA")`, which treats `RSA` as a
  symbol of the `PublicKey` module. If `RSA` is a submodule, it should be
  `load("@vendor//Crypto/PublicKey/RSA", ...)`. py2star can't tell which
  from the source alone.
- Warn on names that are used but never defined or loaded?

## Ideas

- A class that only holds attributes (`class Algo: x = 1; y = 2`) could
  become a module with globals `x` and `y`.
- A command-line interface along the lines of
  [Instagram's Fixit](https://github.com/instagram/fixit).
- More desugaring ideas:
  [pydron](https://github.com/pydron/pydron/tree/master/pydron/translation/dedecorator.py),
  [pythran](https://github.com/serge-sans-paille/pythran/tree/master/pythran/transformations),
  [typy](https://github.com/Procrat/typy/blob/master/typy/insuline.py).

## Done

The README lists everything py2star translates; these were on this roadmap:

- try/except/else/finally (via `Result`), generators and `yield from`,
  `for`/`else` and `while`/`else`, `nonlocal`, `del`, slice assignment
  ([#23](https://github.com/mahmoudimus/py2star/pull/23)).
- `raise` keeps its message, including `.format()` messages; `raise X` with
  no arguments becomes `fail("X")`
  ([#23](https://github.com/mahmoudimus/py2star/pull/23)).
- String formatting, including `"%02x"`, through `format()`
  ([#24](https://github.com/mahmoudimus/py2star/pull/24)).
- `@property` in both class modes
  ([#29](https://github.com/mahmoudimus/py2star/pull/29)).
- `not` in front of a chained comparison; `-t` `TestCase`s with `setUp`
  state, helper methods and `tearDown`; `--use-mutablestruct` constructor
  order (`__init__` calling later methods, class attributes on `self`,
  classes without `__init__`); `warnings.warn` as `print`
  ([#37](https://github.com/mahmoudimus/py2star/pull/37)).
- Relative imports resolved from the file's package, with or without `-p`;
  `.hex()` left to Larky's own; modules made only of imports keep their
  loads ([#35](https://github.com/mahmoudimus/py2star/pull/35)).
- `str.encode` to `codecs.encode`, only where the receiver is a `str`
  ([#31](https://github.com/mahmoudimus/py2star/pull/31)).
- All transformations are libcst passes; the lib2to3 fixers and lib3to6
  were removed ([#22](https://github.com/mahmoudimus/py2star/pull/22)).
- Earlier: decorators, set literals, `a = b = x`, `**`, implicit string
  concatenation, asserts, imports as `load()` sorted to the top,
  `if __name__ == "__main__"` removed.
