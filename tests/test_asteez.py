import logging
import os.path
from pathlib import Path
from textwrap import dedent

import astunparse
import libcst as cst
import pytest
from libcst.codemod import CodemodContext
from libcst.metadata import FullyQualifiedNameProvider
from py2star.asteez import (
    functionz,
    remove_exceptions,
    remove_types,
    rewrite_class,
    rewrite_comparisons,
    rewrite_fstring,
    rewrite_imports,
    rewrite_loopz,
)

logger = logging.getLogger(__name__)


def test_remove_fstring(program):
    rewriter = rewrite_fstring.RemoveFStrings()
    rewritten = rewriter.visit(program)
    code = astunparse.unparse(rewritten)
    assert "raise ValueError(('%s, %s, %s' % (key, mode, nonce)))" in code
    assert "return ('%s' % (foo,))" in code


def test_remove_types(source_tree):
    context = CodemodContext()
    txfrmr = remove_types.RemoveTypesTransformer(context)
    rewritten = source_tree.visit(txfrmr)
    print(rewritten.code)


def test_remove_self(source_tree):
    context = CodemodContext()
    tree = source_tree
    for l in [
        rewrite_class.FunctionParameterStripper(context, ["self"]),
        rewrite_class.AttributeGetter(context, ["self"]),
    ]:
        tree = tree.visit(l)

    # print(tree.code)
    assert "self" not in tree.code


def test_convert_while_loop():
    """
    While loop converted to for loop because there's no while loops in starlark
    :return:
    """
    s = cst.parse_module(
        """
pos = 0
finish = 5
while pos <= finish:
    m = self.search(s, pos)
    if not m:
        res += s[pos:]
        break    
        
    """
    )
    expected = cst.parse_module(
        """
pos = 0
finish = 5
for _while_ in range(_WHILE_LOOP_EMULATION_ITERATION):
    if pos > finish:
        break
    m = self.search(s, pos)
    if not m:
        res += s[pos:]
        break 
            
    """
    )
    ctx = CodemodContext()
    w2f = rewrite_loopz.WhileToForLoop(ctx)
    rewritten = s.visit(w2f)
    assert expected.code.strip() == rewritten.code.strip()


def test_generator_to_comprehension():
    context = CodemodContext()
    tree = cst.parse_module(
        """
c = range(12)
x = (i for i in c)
"""
    )
    gf = functionz.GeneratorToFunction(context)
    rewritten = tree.visit(gf)
    expected = """
c = range(12)
x = [i for i in c]
"""
    assert expected == str(rewritten.code)


def test_unchain_comparison():
    context = CodemodContext()
    tree = cst.parse_module(
        """
def compare(x, y):
    if 1 < x <= y < 10:
        return True
"""
    )
    rwcc = rewrite_comparisons.UnchainComparison(context)
    rewritten = tree.visit(rwcc)
    expected = """
def compare(x, y):
    if (1 < x) and (x <= y) and (y < 10):
        return True
"""
    assert expected.strip() == rewritten.code.strip()


def test_is_comparison_transformer():
    tree = cst.parse_module(
        """
a = False
a is False
b = True
b is not False
"""
    )
    rwcc = rewrite_comparisons.IsComparisonTransformer()
    rewritten = tree.visit(rwcc)
    expected = """
a = False
a == False
b = True
b != False
"""
    assert expected.strip() == rewritten.code.strip()


@pytest.mark.xfail
def test_remove_exceptions():
    """
    try:
        x(y(f(xx)))
    except Exception:
        xx

    _tmp = safe(f)(xx).map(y).map(x)
    :return:
    """
    # https://github.com/MaT1g3R/option/issues/7
    tree = cst.parse_module(
        """
def foo(a, b, c):
    try:
        a(b, c)
    except ZeroDivisionError:
        raise ValueError("cannot divide by zero")
    except Exception:
        raise TypeError("What?")
"""
    )
    context = CodemodContext()
    c2frw = remove_exceptions.RemoveExceptions(context)
    rewritten = tree.visit(c2frw)
    expected = """
def foo(a, b, c):
    _tmp = safe(a)(b, c)
    if _tmp.is_ok:
        return _tmp.unwrap()
    if _tmp.
try_(foo, 
     except_=[
       Error('ZeroDivisionError: ValueError: cannot divide by zero'),
       Error('Exception: TypeError: What?')
    ],
    finally_=[
    ])
  .except_(ZeroDivisionError, ValueError("cannot divide by zero"))
  .except_(Exception, TypeError("What?"))

safe(foo)
  .
"""
    # using split() avoids having to trim trailing whitespace.
    assert _remove_empty_lines(rewritten.code) == _remove_empty_lines(expected)


def test_rewrite_raise_to_error_object():
    tree = cst.parse_module(
        """
def foo(a, b, c):
    if not a:
        raise ValueError("a: %s is not truthy!" % (a,))
"""
    )
    context = CodemodContext()
    c2frw = remove_exceptions.RemoveExceptions(context)
    rewritten = tree.visit(c2frw)
    expected = """
def foo(a, b, c):
    if not a:
        return Error("ValueError: a: %s is not truthy!" % (a,))
"""
    # using split() avoids having to trim trailing whitespace.
    assert _remove_empty_lines(rewritten.code) == _remove_empty_lines(expected)


def test_rewrite_typechecks():
    tree = cst.parse_module(
        """
def foo(a, b, c):
    if isinstance({}, dict):
        return "hello"
    elif callable(lambda : 1):
        return "what?"
"""
    )
    context = CodemodContext()
    c2frw = functionz.RewriteTypeChecks(context)
    rewritten = tree.visit(c2frw)
    # rewritten = c2frw.transform_module(tree)
    expected = """
def foo(a, b, c):
    if types.is_instance({}, dict):
        return "hello"
    elif types.is_callable(lambda : 1):
        return "what?"
"""
    # using split() avoids having to trim trailing whitespace.
    assert _remove_empty_lines(rewritten.code) == _remove_empty_lines(expected)


def test_class_to_function():
    tree = cst.parse_module(
        """
class Foo(object):
    def __init__(self):
        pass

class Bar(object):
    def __init__(self, var, value):
        pass

class Complicated():
    def __init__(self, x, y, z=1):
        pass

    def foo(self, one, two=2):
        pass

    @staticmethod
    def doit(a, b):
        pass
"""
    )
    context = CodemodContext()
    c2frw = rewrite_class.ClassToFunctionRewriter(
        context, remove_decorators=True
    )
    rewritten = tree.visit(c2frw)
    expected = """
def Foo():
    self = larky.mutablestruct(__class__='Foo')
    def __init__():
        pass
        return self
    self = __init__()

    return self

def Bar(var, value):
    self = larky.mutablestruct(__class__='Bar')
    def __init__(var, value):
        pass
        return self
    self = __init__(var, value)

    return self

def Complicated(x, y, z=1):
    self = larky.mutablestruct(__class__='Complicated')
    def __init__(x, y, z):
        pass
        return self
    self = __init__(x, y, z)

    def foo(one, two=2):
        pass
    self.foo = foo
    
    def doit(a, b):
        pass
    self.doit = doit

    return self
"""
    # using split() avoids having to trim trailing whitespace.
    assert _remove_empty_lines(rewritten.code) == _remove_empty_lines(expected)


def _remove_empty_lines(mystr):
    # "".join([s for s in t.strip().splitlines(True)
    #         if s.strip("\r\n").strip()])
    return [line for line in mystr.split("\n") if line.strip() != ""]


def test_rewrite_imports():
    sample = """
    from __future__ import print_function
    
    import unittest
    from binascii import unhexlify
    
    import Crypto.Hash.SHA256
    # TODO: fix this one! ==> from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
    from Crypto.SelfTest.st_common import list_test_cases
    from Crypto.SelfTest.loader import load_test_vectors, load_test_vectors_wycheproof
    
    from Crypto.Util.py3compat import tobytes, bchr
    from Crypto.Cipher import AES
    from Crypto.Hash import SHAKE128, SHA256
    
    from Crypto.Util.strxor import strxor
    # load("@stdlib//unittest")
    """
    tree = cst.parse_module(dedent(sample))
    pkg_root = os.path.basename(__file__)
    wrapper = cst.MetadataWrapper(
        tree,
        cache={
            FullyQualifiedNameProvider: FullyQualifiedNameProvider.gen_cache(
                Path(""), [pkg_root], None
            ).get(pkg_root, "")
        },
    )
    wrapper.resolve_many(rewrite_imports.RewriteImports.METADATA_DEPENDENCIES)
    rwi = rewrite_imports.RewriteImports(
        context=CodemodContext(wrapper=wrapper, filename=pkg_root)
    )
    rewritten = wrapper.visit(rwi)
    expected = """
    load("@stdlib//unittest", unittest="unittest")
    load("@stdlib//binascii", unhexlify="unhexlify")
    
    load("@vendor//Crypto/Hash", SHA256="SHA256")
    # TODO: fix this one! ==> from Crypto.PublicKey import RSA => load("@vendor//Crypto/PublicKey/RSA", "RSA")
    load("@vendor//Crypto/SelfTest/st_common", list_test_cases="list_test_cases")
    load("@vendor//Crypto/SelfTest/loader", load_test_vectors="load_test_vectors", load_test_vectors_wycheproof="load_test_vectors_wycheproof")
    
    load("@vendor//Crypto/Util/py3compat", tobytes="tobytes", bchr="bchr")
    load("@vendor//Crypto/Cipher", AES="AES")
    load("@vendor//Crypto/Hash", SHAKE128="SHAKE128", SHA256="SHA256")
    
    load("@vendor//Crypto/Util/strxor", strxor="strxor")
    # load("@stdlib//unittest")    
"""
    # print(rewritten.code.strip())
    assert dedent(expected).strip() == dedent(rewritten.code).strip()
