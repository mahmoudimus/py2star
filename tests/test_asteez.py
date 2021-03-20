import logging
import ast

import astpretty
import pytest
import astunparse
import libcst as cst
from py2star.asteez import functionz, loopz, rewrite_fstring
from py2star.asteez import remove_types
from py2star.asteez import remove_self
from libcst.codemod import CodemodContext
from py2star.asteez.functionz import GeneratorToFunction

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


def test_remove_self(toplevel_functions):
    tree = toplevel_functions
    for l in [
        remove_self.FunctionParameterStripper(["self"]),
        remove_self.AttributeGetter(["self"]),
    ]:
        tree = l.visit(tree)
    print(astunparse.unparse(tree))


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
    w2f = loopz.WhileToForLoop()
    rewritten = w2f.visit(sut)
    assert expected.strip() == astunparse.unparse(rewritten).strip()


def test_generator_to_comprehension():
    s = ast.parse(
        """
c = range(12)
x = (i for i in c)
    """
    )
    gf = functionz.GeneratorToFunction()
    rewritten = gf.visit(s)
    expected = """
c = range(12)
x = [i for i in c]
"""
    assert expected == astunparse.unparse(rewritten)
