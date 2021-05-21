import ast
import inspect
import string
import textwrap
import typing

import libcst as cst
from libcst import matchers as m
from libcst import Attribute, BaseExpression, Call, Name, codemod
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor


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


class RewriteTypeChecks(codemod.VisitorBasedCodemodCommand):
    def __init__(self, context: CodemodContext):
        super(RewriteTypeChecks, self).__init__(context)

    # types.star currently has...
    def leave_Call(
        self, original_node: "Call", updated_node: "Call"
    ) -> "BaseExpression":
        if m.matches(updated_node, m.Call(func=m.Name("isinstance"))):
            AddImportsVisitor.add_needed_import(
                self.context,
                "types",
                "types",
            )
            # types.is_instance(...)
            #
            return updated_node.with_changes(
                func=Attribute(value=Name("types"), attr=Name("is_instance"))
            )
        elif m.matches(updated_node, m.Call(func=m.Name("callable"))):
            AddImportsVisitor.add_needed_import(
                self.context,
                "types",
                "types",
            )
            return updated_node.with_changes(
                func=Attribute(value=Name("types"), attr=Name("is_callable"))
            )
        return super().leave_Call(original_node, updated_node)
