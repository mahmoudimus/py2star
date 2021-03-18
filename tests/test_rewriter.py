import logging
import os
from argparse import Namespace
from typing import TextIO

import pytest

from py2star import cli

logger = logging.getLogger(__name__)

import ast
import itertools

from py2star import rewriter
from py2star import starify


@pytest.fixture()
def program() -> ast.Module:
    m = ast.parse(open("simple_class.py").read())
    return m


def test_rewrite():
    import io
    from lib2to3 import refactor, pygram, fixer_base
    _fixers = refactor.get_fixers_from_package("py2star.fixes")
    assert isinstance(_fixers, list) and len(_fixers) != 0

    def rt(fixers, options=None, explicit=None):
        return refactor.RefactoringTool(fixers, options, explicit)

    out = open("simple_class.py").read()
    for f in _fixers:
        tool = rt([f])
        out = str(tool.refactor_string(out, "simple_class.py"))
    print(out)


def test_ast_visiting(program):
    visitor = rewriter.FunctionAndMethodVisitor()
    visitor.visit(program)
    for function in itertools.chain(visitor.functions, visitor.methods):
        print(function.name)


def test_starify(program):
    starify.starify(program)

