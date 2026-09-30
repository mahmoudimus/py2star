# py2star
Converts python files to starlark files

## Get started quickly

#### Setup

Requires Python 3.10+.

```bash
python -m venv venv
source venv/bin/activate
pip install -e '.[tests]'
```

#### Run
```bash
py2star larkify path/to/module.py > module.star
py2star larkify -t ~/src/pycryptodome/lib/Crypto/SelfTest/PublicKey/test_RSA.py > test_RSA.star
```

`larkify -t` rewrites `unittest` classes and appends a test suite runner.
`py2star tests file.star` prints just the runner for an existing file.

#### Testing against Larky

`tests/e2e/` holds Python programs that are larkified and run in Larky, and
their output compared with CPython's. They need a JDK and a starlarky build:

```bash
LARKY_JAR=~/src/starlarky/larky/target/larky-1.0.0-SNAPSHOT-jar-with-dependencies.jar pytest tests/test_larky_e2e.py
```

## Differences with Python

The list of differences between Starlark and Python are documented at https://bazel.build site:
- [Differences with Python](https://docs.bazel.build/versions/master/skylark/language.html#differences-with-python)
- More differences documented as a **W**ork **I**n **P**rogress in [this Github issue](https://github.com/bazelbuild/starlark/pull/158)


### Some High-level Differences

- Global variables are immutable.
- `for` statements are not allowed at the top-level. Use them within functions instead.
- `if` statements are not allowed at the top-level. However, `if` expressions can be used: `first = data[0] if len(data) > 0 else None`.
- Deterministic order for iterating through Dictionaries.
- Recursion is not allowed.
- Modifying a collection during iteration is an error.
- Except for equality tests, comparison operators `<`, `<=`, `>=`, `>`, etc. are not defined across value types. In short: `5 < 'foo'` will throw an error and `5 == "5"` will return `False`.
- In tuples, a trailing comma is valid only when the tuple is between parentheses, e.g. `write (1,)` instead of `1,`.
- Dictionary literals cannot have duplicated keys. For example, this is an error: `{"a": 4, "b": 7, "a": 1}`.
- **Strings are represented with double-quotes (e.g. when you call repr).**
- Strings aren't iterable (**WORKAROUND**: use `.elems()` to iterate over it.)
  
### The following Python features are attempted to be automatically converted:

Items marked *verified* are covered by `tests/e2e/` programs whose Larky
output matches CPython (see [Testing against Larky](#testing-against-larky)).

- [x] Builtins Starlark lacks: `sum`, `map` (`builtins.*`), `filter` (list comprehension), `dict.fromkeys` (`larky.dicts.fromkeys`), `bytearray(n)`, `str.encode` (`codecs.encode`), `codecs.encode(b, "hex")` (`binascii`). *verified*
  - Also `issubclass` (`larky.is_subclass`), not yet covered by `tests/e2e/`.
  - Not yet: `round`, `oct`.
- [x] `set` / `frozenset` literals, comprehensions and calls, via [`sets.star`](https://github.com/verygoodsecurity/starlarky/blob/master/larky/src/main/resources/stdlib/sets.star)'s `Set`. *verified*
- [x] Implicit string concatenation (explicit `+`).
- [x] String formatting: f-strings, `str.format()` fields with format specs or `!r`/`!s` conversions, and printf-style `%` with a literal format string become a `str.format()` template with plain `{}` fields; a value with a spec is passed through `format(value, spec)`, and `%r`/`!r` through `repr()`. *verified*
  ```python
  "Invalid %s" % e                  # => "Invalid {}".format(e)
  "%05.1f|%-5s" % (x, y)            # => "{}|{}".format(format(x, "05.1f"), format(str(y), "<5"))
  f"key={k!r} size={n:,}"           # => "key={} size={}".format(repr(k), format(n, ","))
  ```
  - The output needs only plain `{}` fields (standard Starlark) and a `format()` built-in that follows Python's format spec mini-language, which a host can inject, such as [mahmoudimus/starlarky](https://github.com/mahmoudimus/starlarky) (`bc`). It does not depend on the host's `%` or on `str.format()` specs, and it runs unchanged in CPython (only `repr()` quoting differs: `'a'` vs `"a"`).
  - Left as `%`: a format string that is not a literal, `%c`, and precision on an integer conversion (`%.3d`). `%a` becomes `repr()` (Starlark has no `ascii()`).
- [x] Chained comparisons (e.g. `1 < x < 5`).
- [x] `class` (see `larky.struct` function). `@property` / `@x.setter` need `--use-mutablestruct` (`larky.property`). *verified*
- [x] `import` (see `load` statement).
- [x] `while`, including `while/else`; `for/else`. *verified*
- [x] generators (collected into a list, so they must be finite) and generator expressions. *verified*
- [x] `is` and `is not` (use `==`  and `!=` instead, respectively); `type(x) is str` (`types.is_string(x)`). *verified*
- [x] `raise` (`fail("ExcName: message")`; `--use-error-not-fail` returns `Error(...)`, `--unwrap-errors` returns `Error(...).unwrap()`). *verified*
- [x] `try`, `except`, `else`, `finally`, via `Result` from `@vendor//option/result` (see below). *verified*
- [x] `del` (`.pop()`), slice deletion and slice assignment (in place). *verified*
- [x] `nonlocal` (the variable is kept in a one-element list). *verified*
- [ ] `global`: module globals are frozen after a Starlark module loads, so `global` is removed and flagged with a `# PY2LARKY:` comment.

#### How `try/except` is translated

The `try` body becomes a nested function, run with
`Result.Ok(None).map(lambda _: body())`, which catches any error it raises.
Names the body assigns are passed in and returned, and `return` / `break` /
`continue` inside it are re-applied afterwards. Each `except` clause matches
the error message with `Result.error_is`: translated `raise` statements
produce `"ExcName: message"`, and Larky's own runtime errors are matched for
common types (`KeyError`, `IndexError`, `ZeroDivisionError`, `ValueError`,
`AttributeError`, `TypeError`). Limits:

- `except X as e` binds `e` to the message string, not an exception object.
- An exception class matches only its own name, not subclasses (except
  `LookupError` and `ArithmeticError`).
- The `finally` block runs before `return`/`break`/`continue`/`raise`
  statements in `except` and `else` blocks, but not when a call made from
  those blocks raises.

## Automatic Conversion

All transformations are [libcst](https://github.com/Instagram/LibCST) passes in `py2star.asteez`, run in order by `py2star.pipeline`.

* `py2star.asteez.rewrite_tests.Unittest2Functions` -- de-classes and de-indents a `unittest.TestCase`

So, `py2star larkify -t` goes from:

```python
import unittest


class Foo(unittest.TestCase):
    def test_bar(self):
        self.assertEqual(1, 1)
```

To:

```python
load("@stdlib//larky", larky="larky")
load("@stdlib//unittest", unittest="unittest")
load("@vendor//asserts", asserts="asserts")

def Foo_test_bar():
    asserts.assert_that(1).is_equal_to(1)

def _testsuite():
    _suite = unittest.TestSuite()
    _suite.addTest(unittest.FunctionTestCase(Foo_test_bar))
    return _suite

_runner = unittest.TextTestRunner()
_runner.run(_testsuite())
```
