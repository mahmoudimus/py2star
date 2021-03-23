import ast
import logging
from functools import reduce

import astunparse
import libcst as cst
import pytest
from libcst.codemod import CodemodContext
from py2star.asteez import (
    functionz,
    remove_self,
    remove_types,
    rewrite_chained_comparisons,
    rewrite_fstring,
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
        remove_self.FunctionParameterStripper(context, ["self"]),
        remove_self.AttributeGetter(context, ["self"]),
    ]:
        tree = tree.visit(l)

    # print(tree.code)
    assert "self" not in tree.code


def test_convert_while_loop():
    """
    While loop converted to for loop because there's no while loops in starlark
    :return:
    """
    s = ast.parse(
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
    expected = """
pos = 0
finish = 5
for _while_ in range(_WHILE_LOOP_EMULATION_ITERATION):
    if (pos > finish):
        break
    m = self.search(s, pos)
    if (not m):
        res += s[pos:]
        break     
    """
    # print(astunparse.unparse(ast.parse(expected)))
    sut = ast.parse(s)
    # d astpretty.pprint(sut)
    w2f = rewrite_loopz.WhileToForLoop()
    rewritten = w2f.visit(sut)
    assert expected.strip() == astunparse.unparse(rewritten).strip()


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
    rwcc = rewrite_chained_comparisons.UnchainComparison(context)
    rewritten = tree.visit(rwcc)
    expected = """
def compare(x, y):
    if (1 < x) and (x <= y) and (y < 10):
        return True
"""
    assert expected.strip() == rewritten.code.strip()
