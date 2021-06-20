from lib2to3.fixer_base import BaseFix
from lib2to3.fixer_util import token, find_indentation
from lib2to3 import pygram

from py2star.utils import dedent_suite


class FixDeclass(BaseFix):
    explicit = True
    order = "pre"
    run_order = 6  # Fixers will be sorted by run order before execution
    # Lower numbers will be run first.

    PATTERN = """
      classdef< 'class' name=any ['(' 
           ('object')*
      ')'] ':'
         suite=suite
      >
    """

    def transform(self, node, results):
        suite = results["suite"].clone()
        name = results["name"]
        # todo: handle tabs
        dedent = len(find_indentation(suite)) - len(find_indentation(node))
        dedent_suite(suite, dedent)

        # remove the first newline behind the classdef header
        first = suite.children[0]
        if first.type == token.NEWLINE:
            if len(first.value) == 1:
                del suite.children[0]
            else:
                first.value = first.value[1:]
        # function def becomes class_function def
        # i.e. class RewriteMe def test_raises
        #  === RewriteMe_test_raises
        for i in suite.children:
            if i.type == pygram.python_symbols.funcdef:
                n = f"{results['name']}_{i.children[1].value}".strip()
                i.children[1].value = n
        return suite
