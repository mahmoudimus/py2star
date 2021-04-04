import ast
import logging
import pprint
from textwrap import dedent

import astunparse
import libcst as cst
import pytest
from libcst.codemod import CodemodContext
from py2star.asteez import (
    functionz,
    remove_types,
    rewrite_class,
    rewrite_comparisons,
    rewrite_fstring,
    rewrite_imports,
    rewrite_loopz,
)

logger = logging.getLogger(__name__)


@pytest.fixture()
def program() -> ast.Module:
    m = ast.parse(open("simple_class.py").read())
    return m


@pytest.fixture()
def source_tree():
    return cst.parse_module(open("simple_class.py").read())


@pytest.fixture()
def complex_class():
    return ast.parse(open("sample_test.py").read())


@pytest.fixture()
def toplevel_functions():
    return ast.parse(open("toplevelfunctions.py").read())


def test_remove_fstring(program):
    rewriter = rewrite_fstring.RemoveFStrings()
    rewritten = rewriter.visit(program)
    print(astunparse.unparse(rewritten))


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
"""
    )
    c2frw = rewrite_class.ClassToFunctionRewriter()
    rewritten = tree.visit(c2frw)
    expected = """
def Foo():
    def __init__():
        pass
    self = __init__()

    return self

def Bar(var, value):
    def __init__(var, value):
        pass
    self = __init__(var, value)

    return self

def Complicated(x, y, z=1):
    def __init__(x, y, z):
        pass
    self = __init__(x, y, z)

    def foo(one, two=2):
        pass
    self.foo = foo

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
    
    from Crypto.SelfTest.st_common import list_test_cases
    from Crypto.SelfTest.loader import load_test_vectors, load_test_vectors_wycheproof
    
    from Crypto.Util.py3compat import tobytes, bchr
    from Crypto.Cipher import AES
    from Crypto.Hash import SHAKE128, SHA256
    
    from Crypto.Util.strxor import strxor
    # load("@stdlib//unittest")
    """
    tree = cst.parse_module(dedent(sample))
    wrapper = cst.metadata.MetadataWrapper(tree)
    rwi = rewrite_imports.RewriteImports()
    rewritten = wrapper.visit(rwi)
    expected = """
    load("@stdlib//unittest", unittest="unittest")
    load("@stdlib//binascii", unhexlify="unhexlify")
    
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
