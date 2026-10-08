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


def test_property_without_mutablestruct_is_flagged():
    code = larkify(
        """
        class Foo(object):
            @property
            def name(self):
                return 1
        """
    )
    assert "# PY2LARKY: properties need --use-mutablestruct" in code
    # one namespace entry per name: Starlark rejects duplicate dict keys
    assert code.count("'name': name,") == 1


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
