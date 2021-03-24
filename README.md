# py2star
Converts python files to starlark files

## Get started quickly

```bash
python cli.py larkify ~/src/pycryptodome/lib/Crypto/SelfTest/PublicKey/test_RSA.py > test_RSA.star
python cli.py tests test_RSA.star >> test_RSA.star
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

- [ ] most `builtin` functions, most methods.
- [ ] `set` types  (**WORKAROUND**: use [`sets.star`](https://github.com/verygoodsecurity/starlarky/blob/master/larky/src/main/resources/stdlib/sets.star) instead)
- [ ]`implicit string concatenation (use explicit + operator)`.
- [x] Chained comparisons (e.g. 1 < x < 5)`.
- [x] `class` (see `larky.struct` function). 
- [x] `import` (see `load` statement).
- [x] `while`
- [x] `generators` and `generator expressions`.
- [ ] `is` (use `==` instead).
- [ ] `try`, `raise`, `except`, `finally` (see `fail` for fatal errors).
- [ ] `yield`
- [ ] `global`, `nonlocal`.


## Automatic Conversion

* `py2star.fixes.fix_declass` -- de-classes and de-indents a class

So, it goes from:

```python
class Foo(object):
    def bar(self):
        return "baz"
```

To:

```python
def bar(self):
    return "baz"
```