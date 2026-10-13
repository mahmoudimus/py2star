# Roadmap

What py2star still gets wrong or leaves untranslated, checked against
starlarky `master` (`045014db`). Each open item fails today, either in
py2star's output or when that output runs in Larky.

## Open bugs

Wrong output from py2star:

- [ ] `not` in front of a chained comparison applies to the first comparison
  only: `if not 4 <= cost <= 31:` becomes `if not (4 <= cost) and (cost <= 31):`
  instead of `if not ((4 <= cost) and (cost <= 31)):`.
- [ ] `-t`: instance attributes set in `setUp` become locals of the
  `setUp` function, so test functions can't see them:
  `self.x = 1` in `setUp` becomes `x = 1`, and `self.x` in a test becomes an
  undefined `x`.
- [ ] `--use-mutablestruct`: `__init__` runs before the methods defined after
  it are attached to `self`, so `self.v = self.helper()` in `__init__` fails
  when `helper` is defined later in the class.
- [ ] `import warnings` becomes `load("@stdlib//warnings", ...)`, but Larky
  has no `stdlib/warnings.star`. Drop `warnings.warn(...)` calls, or map them
  to `print`.
- [ ] Slice assignment on an object with its own `__getitem__`/`__setitem__`
  (`elem[:] = other`) is rewritten as in-place list operations, which assumes
  a list.

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
- `str.encode` to `codecs.encode`, only where the receiver is a `str`
  ([#31](https://github.com/mahmoudimus/py2star/pull/31)).
- All transformations are libcst passes; the lib2to3 fixers and lib3to6
  were removed ([#22](https://github.com/mahmoudimus/py2star/pull/22)).
- Earlier: decorators, set literals, `a = b = x`, `**`, implicit string
  concatenation, asserts, imports as `load()` sorted to the top,
  `if __name__ == "__main__"` removed.
