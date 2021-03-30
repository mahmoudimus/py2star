import ast
import inspect
import string
import textwrap
import typing

import libcst as cst
from libcst import codemod
from libcst.codemod import CodemodContext


def testsuite_generator(tree):
    all_functions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and "test" in node.name
    ]

    test_cases = textwrap.indent(
        "\n".join(
            [
                f"_suite.addTest(unittest.FunctionTestCase({function_name}))"
                for function_name in all_functions
            ]
        ),
        prefix="    ",
    )
    s = textwrap.dedent(
        """
    def _testsuite():
        _suite = unittest.TestSuite()
    $cases
        return _suite

    _runner = unittest.TextTestRunner()
    _runner.run(_testsuite())
    """
    )
    s = string.Template(s).substitute(cases=test_cases)
    s = inspect.cleandoc(s)
    return s


class GeneratorToFunction(codemod.VisitorBasedCodemodCommand):
    def __init__(self, context: CodemodContext):
        super(GeneratorToFunction, self).__init__(context)

    def leave_GeneratorExp(
        self,
        original_node: cst.GeneratorExp,
        updated_node: cst.GeneratorExp,
    ) -> typing.Union[cst.BaseList, cst.RemovalSentinel]:
        return updated_node.deep_replace(
            updated_node,
            cst.ListComp(elt=updated_node.elt, for_in=updated_node.for_in),
        )
