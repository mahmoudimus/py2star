import ast
import inspect
import string
import textwrap


def testsuite_generator(tree):
    all_functions = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
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


class GeneratorToFunction(ast.NodeTransformer):
    def visit_GeneratorExp(self, node):
        self.generic_visit(node)
        new_node = ast.ListComp(node.elt, node.generators)

        # Tie up loose ends in the AST.
        ast.copy_location(new_node, node)
        ast.fix_missing_locations(new_node)
        return new_node


class FunctionToGenerator(ast.NodeTransformer):
    """
    This subclass traverses the AST of the user-written, decorated,
    model specification and transforms it into a generator for the
    model. Subclassing in this way is the idiomatic way to transform
    an AST.
    Specifically:

    1. Add `yield` keywords to all assignments
       E.g. `x = tfd.Normal(0, 1)` -> `x = yield tfd.Normal(0, 1)`
    2. Rename the model specification function to
       `_pm_compiled_model_generator`. This is done out an abundance
       of caution more than anything.
    3. Remove the @Model decorator. Otherwise, we risk running into
       an infinite recursion.
    """

    def visit_Assign(self, node):
        new_node = node
        new_node.value = ast.Yield(value=new_node.value)

        # Tie up loose ends in the AST.
        ast.copy_location(new_node, node)
        ast.fix_missing_locations(new_node)
        self.generic_visit(node)
        return new_node

    def visit_FunctionDef(self, node):
        new_node = node
        new_node.name = "_pm_compiled_model_generator"
        new_node.decorator_list = []

        # Tie up loose ends in the AST.
        ast.copy_location(new_node, node)
        ast.fix_missing_locations(new_node)
        self.generic_visit(node)
        return new_node
