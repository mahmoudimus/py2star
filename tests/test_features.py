"""
Before/after cases for the passes that translate Python features Starlark
lacks (try/except, generators, nonlocal, slices, ...). tests/test_larky_e2e.py
checks that the translated programs behave like CPython when run in Larky.
"""
import pathlib
import re
import string
import textwrap

import libcst as cst
import libcst.matchers as m
import pytest
from libcst.codemod import CodemodContext

from py2star import pipeline
from py2star.asteez import (
    desugar,
    functionz,
    remove_exceptions,
    rewrite_loopz,
    rewrite_scopes,
)


def transform(transformer, source, **config):
    context = CodemodContext(scratch={"config": config})
    module = cst.parse_module(textwrap.dedent(source))
    return transformer(context).transform_module(module).code


CASES = [
    pytest.param(
        remove_exceptions.RemoveExceptions,
        {},
        r"""
        def f(name, args):
            raise TypeError(
                "{} takes at most 1 positional argument"
                " ({} given)".format(name, len(args))
            )
            raise ValueError()
            raise ValueError(msg)
            raise errors.JWKError("bad " + x)
        """,
        r"""
        def f(name, args):
            fail("TypeError: " + "{} takes at most 1 positional argument"
                " ({} given)".format(name, len(args)))
            fail("ValueError")
            fail("ValueError: " + str(msg))
            fail("JWKError: " + "bad " + x)
        """,
        id='raise format',
    ),
    pytest.param(
        remove_exceptions.RemoveExceptions,
        {'use_error_not_fail': True, 'unwrap_errors': True},
        r"""
        def f(x):
            raise ValueError("Foo")
        """,
        r"""
        def f(x):
            return Error("ValueError: Foo").unwrap()
        """,
        id='raise unwrap',
    ),
    pytest.param(
        remove_exceptions.RemoveExceptions,
        {'use_error_not_fail': True},
        r"""
        def f(x):
            try:
                raise ValueError("in body")
            except ValueError:
                raise ValueError("in handler")
        """,
        r"""
        def f(x):
            try:
                return Error("ValueError: in body").unwrap()
            except ValueError:
                return Error("ValueError: in handler")
        """,
        id='raise in try body, error mode',
    ),
    pytest.param(
        remove_exceptions.TryExceptToResult,
        {},
        r"""
        def f(d, k):
            try:
                v = d[k]
            except KeyError as e:
                v = None
            return v
        """,
        r"""
        def f(d, k):
            def _try_1():
                v = None
                v = d[k]
                return (0, None, (v,))
            _try_1_r = Result.Ok(None).map(lambda _: _try_1())
            if _try_1_r.is_ok:
                _try_1_k, _try_1_v, (v,) = _try_1_r.unwrap()
            elif Result.error_is("^KeyError(:|$)|not found in dictionary", _try_1_r):
                e = _try_1_r.unwrap_err()
                if e.startswith(("KeyError: ",)):
                    e = e.partition(': ')[2]
                v = None
            else:
                _try_1_r.unwrap()
            return v
        """,
        id='try basic',
    ),
    pytest.param(
        remove_exceptions.TryExceptToResult,
        {},
        r"""
        def f(d, log):
            try:
                return d["a"]
            except Exception:
                log.append("x")
                raise
            finally:
                log.append("done")
        """,
        r"""
        def f(d, log):
            def _try_1():
                return (1, d["a"], ())
                return (0, None, ())
            _try_1_r = Result.Ok(None).map(lambda _: _try_1())
            _try_1_k = 0
            if _try_1_r.is_ok:
                _try_1_k, _try_1_v, _ = _try_1_r.unwrap()
            else:
                log.append("x")
                log.append("done")
                _try_1_r.unwrap()
            log.append("done")
            if _try_1_k == 1:
                return _try_1_v
        """,
        id='try finally return reraise',
    ),
    pytest.param(
        rewrite_loopz.ForElseToFlag,
        {},
        r"""
        def f(xs):
            for x in xs:
                if x:
                    break
                for y in x:
                    break
            else:
                print("none")
        """,
        r"""
        def f(xs):
            _broke_1 = False
            for x in xs:
                if x:
                    _broke_1 = True; break
                for y in x:
                    break
            if not _broke_1:
                print("none")
        """,
        id='for else',
    ),
    pytest.param(
        rewrite_loopz.WhileToForLoop,
        {},
        r"""
        def f(i, q):
            while i < 3:
                if q:
                    break
                i += 1
            else:
                print("done")
            while True:
                q.pop()
        """,
        r"""
        def f(i, q):
            _while_broke_1 = False
            for _while_ in range(WHILE_LOOP_EMULATION_ITERATION):
                if i >= 3:
                    break
                if q:
                    _while_broke_1 = True; break
                i += 1
            if not _while_broke_1:
                print("done")
            for _while_ in range(WHILE_LOOP_EMULATION_ITERATION):
                q.pop()
        """,
        id='while else + true',
    ),
    pytest.param(
        rewrite_scopes.BoxNonlocals,
        {},
        r"""
        def counter(start):
            count = 0
            def inc():
                nonlocal count, start
                count += start
                return count
            inc()
            return count
        """,
        r"""
        def counter(start):
            count = [None]
            start = [start]
            count[0] = 0
            def inc():
                count[0] += start[0]
                return count[0]
            inc()
            return count[0]
        """,
        id='nonlocal',
    ),
    pytest.param(
        rewrite_scopes.FlagGlobals,
        {},
        r"""
        _n = 0
        def inc():
            global _n
            _n += 1
        """,
        r"""
        _n = 0
        def inc():
            # PY2LARKY: `global _n` is not supported; module globals are frozen after load
            pass
            _n += 1
        """,
        id='global',
    ),
    pytest.param(
        desugar.RemoveDelKeyword,
        {},
        r"""
        def f(d, l, i):
            del d["a"], d["b"]
            del l[1:3]
            del l[i + 1:]
            del l[::2]
            del x
        """,
        r"""
        def f(d, l, i):
            d.pop("a")
            d.pop("b")
            _lo_d1 = len(l[:1])
            _hi_d1 = max(_lo_d1, len(l[:3]))
            for _ in range(_hi_d1 - _lo_d1):
                l.pop(_lo_d1)
            _lo_d2 = len(l[:i + 1])
            _hi_d2 = len(l)
            for _ in range(_hi_d2 - _lo_d2):
                l.pop(_lo_d2)
            # PY2LARKY: unsupported del (extended slice)
            del l[::2]
            # del x
            pass
        """,
        id='del',
    ),
    pytest.param(
        desugar.RewriteSliceAssignment,
        {},
        r"""
        def f(seq, i, other):
            seq[i:] = other
            seq[:] = b"\x00"
            seq[0] = 1
        """,
        r"""
        def f(seq, i, other):
            _new_s1 = list(other)
            _lo_s1 = len(seq[:i])
            _hi_s1 = len(seq)
            for _ in range(_hi_s1 - _lo_s1):
                seq.pop(_lo_s1)
            for _i, _v in enumerate(_new_s1):
                seq.insert(_lo_s1 + _i, _v)
            # PY2LARKY: slice assignment of bytes is not supported
            seq[:] = b"\x00"
            seq[0] = 1
        """,
        id='slice assign',
    ),
    pytest.param(
        desugar.RewriteBuiltins,
        {},
        r"""
        def f(xs, n, fn):
            a = sum(xs)
            b = map(fn, xs)
            c = filter(None, xs)
            d = filter(fn, xs)
            k = filter(lambda v: v > 1, xs)
            e = set(xs), frozenset()
            g = dict.fromkeys(xs, [])
            h = bytearray(n), bytearray(len(xs) + 1), bytearray(xs)
            return issubclass(a, b)

        def g(sum):
            return sum(1)
        """,
        r"""
        def f(xs, n, fn):
            a = builtins.sum(xs)
            b = builtins.map(fn, xs)
            c = [_x for _x in xs if _x]
            d = [_x for _x in xs if fn(_x)]
            k = [_x for _x in xs if (lambda v: v > 1)(_x)]
            e = Set(xs), Set()
            g = larky.dicts.fromkeys(xs, [])
            h = bytearray(n), bytearray(b"\x00" * (len(xs) + 1)), bytearray(xs)
            return larky.is_subclass(a, b)

        def g(sum):
            return sum(1)
        """,
        id='builtins',
    ),
    pytest.param(
        desugar.DesugarSetSyntax,
        {},
        r"""
        def f(x):
            return {1, x}, {y for y in x}
        """,
        r"""
        def f(x):
            return Set([1, x]), Set([y for y in x])
        """,
        id='set literals',
    ),
    pytest.param(
        desugar.SubMethodsWithLibraryCallsInstead,
        {},
        r"""
        def f(s, b):
            x = s.encode("utf-8", "ignore")
            y = s.encode()
            z = codecs.encode(b, "hex")
            w = codecs.decode(b, "hex")
            v = foo.bar(s).encode(errors="strict")
            return b.decode("latin-1")
        """,
        r"""
        def f(s, b):
            x = codecs.encode(s, encoding="utf-8", errors="ignore")
            y = codecs.encode(s, encoding="utf-8")
            z = binascii.hexlify(b)
            w = binascii.unhexlify(b)
            v = codecs.encode(foo.bar(s), encoding="utf-8", errors="strict")
            return b.decode("latin-1")
        """,
        id='codecs',
    ),
    pytest.param(
        functionz.RewriteTypeChecks,
        {},
        r"""
        def f(x):
            a = type(x) is str
            b = dict == type(x)
            c = type(x) is not list
            d = type(x) == Foo
        """,
        r"""
        def f(x):
            a = types.is_string(x)
            b = types.is_dict(x)
            c = not types.is_list(x)
            d = type(x) == Foo
        """,
        id='type checks',
    ),
]


@pytest.mark.parametrize("transformer,config,before,after", CASES)
def test_transform(transformer, config, before, after):
    got = transform(transformer, before, **config)
    assert got.strip() == textwrap.dedent(after).strip()


def larkify(source, **options):
    return pipeline.larkify(
        textwrap.dedent(source), options=pipeline.Options(**options)
    ).code


def test_property_with_mutablestruct():
    code = larkify(
        """
        class Temp(object):
            @property
            def celsius(self):
                return self._c

            @celsius.setter
            def celsius(self, v):
                self._c = v
        """,
        use_mutablestruct=True,
    )
    assert "self.celsius = larky.property(celsius)\n" in code
    assert "def _set_celsius(v):" in code
    assert "self.celsius = larky.property(celsius, _set_celsius)\n" in code
    assert "@property" not in code and ".setter" not in code


def test_mutablestruct_init_keeps_outer_default():
    code = larkify(
        """
        class Counter(object):
            def __init__(self, start=0):
                self.n = start
        """,
        use_mutablestruct=True,
    )
    assert "def Counter(start=0):" in code
    assert "def __init__(start):" in code
    assert "self = __init__(start)" in code


@pytest.mark.parametrize("default", ["", "=2"])
def test_mutablestruct_init_forwards_variadic_arguments(default):
    code = larkify(
        f"""
        class Counter(object):
            def __init__(self, a, b{default}, *args, **kwargs):
                self.values = (a, b, args, kwargs)
        """,
        use_mutablestruct=True,
    )
    assert f"def Counter(a, b{default}, *args, **kwargs):" in code
    assert "def __init__(a, b, args, kwargs):" in code
    assert "self = __init__(a, b, args, kwargs)" in code


@pytest.mark.parametrize("default", ["", "=3"])
def test_mutablestruct_init_preserves_parameter_order(default):
    code = larkify(
        f"""
        class Ordered(object):
            def __init__(self, a, /, b, *, c{default}):
                self.values = (a, b, c)
        """,
        use_mutablestruct=True,
    )
    assert f"def Ordered(a, /, b, *, c{default}):" in code
    assert "def __init__(a, b, c):" in code
    assert "self = __init__(a, b, c)" in code


def test_mutablestruct_init_removes_self_only_posonly_group():
    code = larkify(
        """
        class Counter(object):
            def __init__(self, /, start=0):
                self.n = start
        """,
        use_mutablestruct=True,
    )
    assert "def Counter(start=0):" in code
    assert "def __init__(start):" in code
    assert "self = __init__(start)" in code


def test_property_with_new_class():
    code = larkify(
        """
        class Temp(object):
            @property
            def name(self):
                return 1

            @property
            def celsius(self):
                return self._c

            @celsius.setter
            def celsius(self, v):
                self._c = v
        """
    )
    assert "def _get_name(self):" in code
    assert "name = larky.property(_get_name)\n" in code
    assert "def _get_celsius(self):" in code
    assert "def _set_celsius(self, v):" in code
    assert "celsius = larky.property(_get_celsius, _set_celsius)\n" in code
    assert "@property" not in code and ".setter" not in code
    assert "PY2LARKY" not in code
    assert 'load("@stdlib//larky", larky="larky")' in code
    # one namespace entry per property, none for the renamed accessors
    assert code.count("'name': name,") == 1
    assert code.count("'celsius': celsius,") == 1
    assert "'_get_" not in code and "'_set_" not in code


def test_setter_without_getter_in_class_is_flagged():
    code = larkify(
        """
        class Child(Base):
            @name.setter
            def name(self, v):
                self._n = v
        """
    )
    assert "# PY2LARKY: setter for name has no getter in this class" in code


def test_class_namespace_skips_nested_functions():
    code = larkify(
        """
        class A(object):
            def m(self):
                def helper():
                    return 1
                return helper()
        """
    )
    assert "'helper'" not in code
    assert "types.new_class('A', (object,), {}" in code
    assert 'load("@stdlib//types", types="types")' in code


def test_nested_function_in_init_keeps_its_name():
    code = larkify(
        """
        class A(object):
            def __init__(self):
                def helper():
                    return 1
                self.x = helper()
        """,
        use_mutablestruct=True,
    )
    assert "def helper():" in code
    assert "self.helper" not in code


def test_fstrings_are_rewritten():
    code = larkify(
        """
        def f(x):
            return f"{x!r}: {x:>4}"
        """
    )
    assert 'return "{}: {}".format(repr(x), format(x, ">4"))' in code


@pytest.mark.parametrize(
    "program",
    sorted((pathlib.Path(__file__).parent / "e2e").glob("*.py")),
    ids=lambda p: p.stem,
)
def test_output_formatting_is_portable(program):
    """Hosts can supply format(), but not always a Python-compatible % or
    str.format(): output may use neither % formatting nor str.format()
    fields with format specs or conversions."""
    source = program.read_text()
    match = re.match(r"# options: (.*)", source)
    options = eval(f"dict({match.group(1)})") if match else {}
    code = larkify(source, **options)

    class _Percent(cst.CSTVisitor):
        found = []

        def visit_BinaryOperation(self, node):
            if isinstance(node.operator, cst.Modulo) and isinstance(
                node.left, (cst.SimpleString, cst.ConcatenatedString)
            ):
                self.found.append(cst.Module([]).code_for_node(node))

        def visit_Call(self, node):
            if m.matches(
                node, m.Call(func=m.Attribute(value=m.SimpleString(), attr=m.Name("format")))
            ):
                template = node.func.value.evaluated_value
                for _, field, spec, conversion in string.Formatter().parse(template):
                    if field is not None and (spec or conversion):
                        self.found.append(cst.Module([]).code_for_node(node))

    visitor = _Percent()
    visitor.found = []
    cst.parse_module(code).visit(visitor)
    assert visitor.found == []


def test_translated_formatting_runs_the_same_in_cpython(capsys):
    """The formatting output uses only format(), str(), repr() and plain
    str.format() fields, so the .star file also runs in CPython."""
    program = pathlib.Path(__file__).parent / "e2e" / "formatting.py"
    source = program.read_text()
    exec(compile(source, str(program), "exec"), {})
    expected = capsys.readouterr().out

    star = larkify(source)
    body = "\n".join(
        line for line in star.splitlines() if not line.startswith("load(")
    )
    exec(compile(body, "formatting.star", "exec"), {})
    assert capsys.readouterr().out == expected


def test_encode_rewrite_only_for_str_encode():
    """#27: only calls shaped like str.encode become codecs.encode."""
    code = larkify(
        """
        import json
        from jose import jwt

        def f(s, enc, encoder):
            a = jwt.encode(claims, key, algorithm="HS256")
            b = jwt.encode(claims)
            c = json.JSONEncoder().encode(obj)
            d = encoder.encode(obj)
            e = s.encode(enc)
            g = s.encode("utf-8")
            h = s.encode()
            i = s.encode(encoding=enc, errors="ignore")
            k = encoder.encode("v", ":")
            return a, b, c, d, e, g, h, i, k
        """
    )
    for unchanged in (
        'encoder.encode("v", ":")',
        'jwt.encode(claims, key, algorithm="HS256")',
        "jwt.encode(claims)",
        "json.JSONEncoder().encode(obj)",
        "encoder.encode(obj)",
        "s.encode(enc)",
    ):
        assert unchanged in code
    assert 'g = codecs.encode(s, encoding="utf-8")' in code
    assert 'h = codecs.encode(s, encoding="utf-8")' in code
    assert 'i = codecs.encode(s, encoding=enc, errors="ignore")' in code


def test_top_level_try_blocks_are_commented_out():
    """#28: every top-level try is commented out, and the module stays valid."""
    code = larkify(
        """
        import unittest

        # fast path
        try:
            import ujson as json
        except ImportError:
            import json

        X = 1

        try:
            from datetime import UTC
        except ImportError:
            UTC = None


        class Thing(object):
            pass

        try:
            import last
        except ImportError:
            last = None
        """
    )
    assert "# fast path\n# try:\n#     import ujson as json\n" in code
    assert "# try:\n#     from datetime import UTC\n# except ImportError:\n#     UTC = None\n" in code
    # comments above a class survive the class rewrite
    assert code.index("#     UTC = None") < code.index("def _class_Thing")
    # a try at the very end goes to the module footer
    assert code.rstrip().endswith("#     last = None")
    cst.parse_module(code)


def test_tests_mode_translates_helper_classes():
    """#30: -t no longer crashes on classes that are not TestCases, and only
    TestCase methods get the test treatment."""
    code = larkify(
        """
        import unittest

        class Helper(object):
            LIMIT = 3

            def __init__(self, n):
                self.n = n

            def double(self):
                return self.n * 2

        class TestThing(unittest.TestCase):
            def test_one(self):
                def chunk(x):
                    return x
                self.assertEqual(chunk(Helper(2).double()), 4)

        def standalone(self):
            return self
        """,
        for_tests=True,
    )
    assert "def _class_Helper():" in code
    assert "def __init__(self, n):\n        self.n = n" in code
    assert "def double(self):\n        return self.n * 2" in code
    assert "def TestThing_test_one():" in code
    # nested functions and top-level functions keep their names
    assert "def chunk(x):" in code
    assert "def standalone(self):" in code


def test_encode_rewrite_uses_receiver_type():
    """A receiver known to be a str accepts any str.encode-shaped call; one
    known not to be a str never matches; otherwise the literal rule holds."""
    code = larkify(
        """
        from jose import jwt

        class Codec(object):
            def encode(self, value, sep):
                return value

        def f(y, enc, flag, maybe, x2: str):
            x = "abc"
            a = x.encode(enc)
            b = str(y).encode(enc, "ignore")
            c = x2.encode(enc)
            if flag:
                z = "s"
            else:
                z = y
            d = z.encode(enc)
            if flag:
                q = "s"
            else:
                q = "t" + y
            e = q.encode(enc)
            k = Codec()
            g = k.encode("utf-8", "strict")
            num = 3
            h = num.encode("utf-8")
            i = jwt.encode(enc)
            j = maybe.encode("utf-8")
            l = maybe.encode(enc)
            return a, b, c, d, e, g, h, i, j, l
        """
    )
    # known str: any str.encode-shaped call
    assert "a = codecs.encode(x, encoding=enc)" in code
    assert 'b = codecs.encode(str(y), encoding=enc, errors="ignore")' in code
    assert "c = codecs.encode(x2, encoding=enc)" in code
    assert "e = codecs.encode(q, encoding=enc)" in code
    # one branch is not known to be a str
    assert "d = z.encode(enc)" in code
    # known not str: never
    assert 'g = k.encode("utf-8", "strict")' in code
    assert 'h = num.encode("utf-8")' in code
    assert "i = jwt.encode(enc)" in code
    # unknown: only literal codec arguments
    assert 'j = codecs.encode(maybe, encoding="utf-8")' in code
    assert "l = maybe.encode(enc)" in code


def _package_tree(tmp_path):
    """tmp/proj/jose/{__init__,jws}.py and tmp/proj/jose/backends/{__init__,base}.py"""
    pkg = tmp_path / "proj" / "jose"
    (pkg / "backends").mkdir(parents=True)
    for f in ("__init__.py", "jws.py", "backends/__init__.py", "backends/base.py"):
        (pkg / f).write_text("")
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "mod.py").write_text("")
    return pkg


@pytest.mark.parametrize(
    "pkg_path,relpath,expected",
    [
        (None, "proj/jose/jws.py", "jose.jws"),
        (None, "proj/jose/backends/base.py", "jose.backends.base"),
        ("jose", "proj/jose/backends/base.py", "jose.backends.base"),
        ("jose", "proj/jose/__init__.py", "jose.__init__"),
        ("jose.backends", "proj/jose/backends/base.py", "jose.backends.base"),
        (None, "loose/mod.py", "loose.mod"),
        ("mypkg", "loose/mod.py", "mypkg.mod"),
    ],
)
def test_full_module_name_from_the_file_system(tmp_path, monkeypatch, pkg_path, relpath, expected):
    """#33/#34: the module name comes from __init__.py files, whatever the
    working directory or path form."""
    from py2star.cli import _full_module_name

    _package_tree(tmp_path)
    absolute = str(tmp_path / relpath)
    assert _full_module_name(pkg_path, absolute) == expected
    monkeypatch.chdir(tmp_path)
    assert _full_module_name(pkg_path, relpath) == expected
    monkeypatch.chdir("/")
    assert _full_module_name(pkg_path, absolute) == expected


def test_relative_imports_resolve_against_the_package(tmp_path):
    from py2star.cli import _full_module_name

    pkg = _package_tree(tmp_path)
    source = "from . import get_random_bytes\nfrom .base import Key\nfrom ..utils import b64\n"
    code = pipeline.larkify(
        source,
        full_module_name=_full_module_name(None, str(pkg / "backends" / "base.py")),
    ).code
    assert 'load("@vendor//jose/backends", get_random_bytes="get_random_bytes")' in code
    assert 'load("@vendor//jose/backends/base", Key="Key")' in code
    assert 'load("@vendor//jose/utils", b64="b64")' in code
    init = pipeline.larkify(
        "from .exceptions import JOSEError\n",
        full_module_name=_full_module_name(None, str(pkg / "__init__.py")),
    ).code
    assert 'load("@vendor//jose/exceptions", JOSEError="JOSEError")' in init


def test_unresolvable_relative_import_is_left_as_written(capsys):
    """#33: no module name at all (no file): leave it, don't crash."""
    code = pipeline.larkify("from . import jwk\nfrom .base import Key\n").code
    assert "from . import jwk" in code
    assert "from .base import Key" in code
    assert "cannot resolve relative import" in capsys.readouterr().err


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "import json\nfrom os import path\n",
            'load("@stdlib//json", json="json")\nload("@stdlib//os", path="path")',
        ),
        ('"""doc"""\nimport json\n', '"""doc"""\nload("@stdlib//json", json="json")'),
        ("import json\nX = 1\n", 'load("@stdlib//json", json="json")\nX = 1'),
    ],
)
def test_loads_kept_in_import_only_modules(source, expected):
    """Modules made only of imports (re-export __init__.py files) used to
    lose every load, and a docstring was duplicated."""
    assert pipeline.larkify(source).code.strip() == expected


def test_tests_mode_keeps_testcase_state():
    """setUp state, helper methods and tearDown work: the TestCase becomes a
    mutablestruct constructor and each test a wrapper around a fresh one."""
    code = larkify(
        """
        import unittest

        class T(unittest.TestCase):
            def setUp(self):
                self.x = 1

            def helper(self, n):
                return n + self.x

            def test_x(self):
                self.assertEqual(self.helper(1), 2)

            def tearDown(self):
                self.x = None
        """,
        for_tests=True,
    )
    assert "self = larky.mutablestruct(__name__='T', __class__=T)" in code
    assert "    def setUp():\n        self.x = 1\n" in code
    assert "asserts.assert_that(self.helper(1)).is_equal_to(2)" in code
    assert (
        "def T_test_x():\n"
        "    _t = T()\n"
        "    _t.setUp()\n"
        "    _r = Result.Ok(None).map(lambda _: _t.test_x())\n"
        "    _t.tearDown()\n"
        "    _r.unwrap()\n"
    ) in code


def test_warnings_become_prints():
    code = larkify(
        """
        import warnings
        from warnings import warn as w

        def f(msg):
            warnings.warn("careful")
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            w("aliased", category=RuntimeWarning)
            warnings.simplefilter("ignore")
        """
    )
    assert "warnings" not in code.replace('warnings.simplefilter("ignore") has no', "")
    assert 'print("UserWarning: careful")' in code
    assert 'print("DeprecationWarning: " + str(msg))' in code
    assert 'print("RuntimeWarning: aliased")' in code
    assert '# PY2LARKY: warnings.simplefilter("ignore") has no Larky equivalent' in code


def test_mutablestruct_constructor_order():
    """self exists before any method is attached, class attributes are set on
    self, and __init__ runs after every method exists."""
    code = larkify(
        """
        class A(object):
            LIMIT = 3

            def helper(self):
                return self.LIMIT

            def __init__(self, n):
                self.n = self.later(n)

            def later(self, n):
                return n

        class NoInit(object):
            def m(self):
                return 1
        """,
        use_mutablestruct=True,
    )
    a = code[code.index("def A("):code.index("def NoInit(")]
    assert a.index("self = larky.mutablestruct") < a.index("def helper")
    assert "    LIMIT = 3\n    self.LIMIT = LIMIT\n" in a
    assert a.index("self.later = later") < a.index("self = __init__(n)") < a.rindex("return self")
    assert "self = larky.mutablestruct(__name__='NoInit', __class__=NoInit)" in code
    assert code.count('load("@stdlib//larky"') == 1


@pytest.mark.parametrize(
    "source, needs_larky",
    [
        ("def f(x):\n    return g(x)\n", False),
        ("def f(x):\n    return isinstance(x, int) or callable(x)\n", False),
        ("def f(a, b):\n    return issubclass(a, b)\n", True),
    ],
)
def test_larky_loaded_only_when_used(source, needs_larky):
    code = larkify(source)
    assert ('load("@stdlib//larky"' in code) == needs_larky
    assert ("larky." in code) == needs_larky
