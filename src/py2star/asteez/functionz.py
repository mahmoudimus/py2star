import inspect
import string
import textwrap
import typing

import libcst as cst
from libcst import matchers as m
from libcst import Attribute, BaseExpression, Call, Name, codemod
from libcst.codemod.visitors import AddImportsVisitor


def testsuite_generator(tree: cst.Module):
    all_functions = [
        node.name.value
        for node in tree.body
        if isinstance(node, cst.FunctionDef) and "test" in node.name.value
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


class _YieldFinder(cst.CSTVisitor):
    """Finds yields that belong to this function (not nested scopes)."""

    def __init__(self) -> None:
        self.statements = False  # yield used as a statement
        self.expressions = False  # yield used as a value (x = yield ...)
        self._statement_yields = set()

    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False

    def visit_Lambda(self, node) -> bool:
        return False

    def visit_Expr(self, node: cst.Expr) -> None:
        if isinstance(node.value, cst.Yield):
            self.statements = True
            self._statement_yields.add(node.value)

    def visit_Yield(self, node: cst.Yield) -> None:
        if node not in self._statement_yields:
            self.expressions = True


class _CollectYields(cst.CSTTransformer):
    def __init__(self, name: str) -> None:
        self.name = name

    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False

    def visit_Lambda(self, node) -> bool:
        return False

    def leave_Expr(self, original_node: cst.Expr, updated_node: cst.Expr):
        y = updated_node.value
        if not isinstance(y, cst.Yield):
            return updated_node
        if isinstance(y.value, cst.From):
            method, value = "extend", y.value.item
        else:
            method, value = "append", y.value or cst.Name("None")
        return updated_node.with_changes(
            value=cst.Call(
                func=cst.Attribute(value=cst.Name(self.name), attr=cst.Name(method)),
                args=[cst.Arg(value)],
            )
        )

    def leave_Return(self, original_node, updated_node):
        # a generator's return value is not part of what it yields
        return updated_node.with_changes(
            value=cst.Name(self.name),
            whitespace_after_return=cst.SimpleWhitespace(" "),
        )


class GeneratorToFunction(codemod.ContextAwareTransformer):
    """
    Starlark has no generators. A generator function collects what it
    yields into a list and returns it (so it must be finite):

        def gen(n):
            for i in range(n):
                yield i
            yield from other()

    becomes:

        def gen(n):
            _yielded = []
            for i in range(n):
                _yielded.append(i)
            _yielded.extend(other())
            return _yielded

    Generator expressions become list comprehensions.
    """

    RESULT = "_yielded"

    def leave_GeneratorExp(
        self,
        original_node: cst.GeneratorExp,
        updated_node: cst.GeneratorExp,
    ) -> typing.Union[cst.BaseList, cst.RemovalSentinel]:
        return updated_node.deep_replace(
            updated_node,
            cst.ListComp(elt=updated_node.elt, for_in=updated_node.for_in),
        )

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        finder = _YieldFinder()
        for stmt in original_node.body.body:
            stmt.visit(finder)
        if not finder.statements:
            return updated_node
        if finder.expressions:
            # "x = yield y" (coroutines) cannot be emulated; leave it for a
            # manual port.
            return updated_node
        body = [
            stmt.visit(_CollectYields(self.RESULT))
            for stmt in updated_node.body.body
        ]
        docstring = (
            body[:1]
            if body and m.matches(
                body[0], m.SimpleStatementLine([m.Expr(m.SimpleString())])
            )
            else []
        )
        body = (
            docstring
            + [cst.parse_statement(f"{self.RESULT} = []")]
            + body[len(docstring):]
            + [cst.parse_statement(f"return {self.RESULT}")]
        )
        return updated_node.with_changes(
            body=updated_node.body.with_changes(body=body)
        )


_TYPE_PREDICATES = {
    "str": "is_string",
    "dict": "is_dict",
    "list": "is_list",
    "tuple": "is_tuple",
    "int": "is_int",
    "float": "is_float",
    "bool": "is_bool",
    "bytes": "is_bytes",
    "bytearray": "is_bytearray",
    "set": "is_set",
}


class RewriteTypeChecks(codemod.ContextAwareTransformer):
    """
    isinstance(x, T)   => builtins.isinstance(x, T)
    callable(x)        => types.is_callable(x)
    type(x) is str     => types.is_string(x)   (also ==, is not, !=)

    In Starlark, type(x) is a string such as "string", so comparing it to
    the builtin str is always False.
    """

    def leave_Comparison(
        self, original_node: cst.Comparison, updated_node: cst.Comparison
    ) -> cst.BaseExpression:
        if len(updated_node.comparisons) != 1:
            return updated_node
        left = updated_node.left
        target = updated_node.comparisons[0]
        right = target.comparator
        type_call = m.Call(func=m.Name("type"), args=[m.Arg(keyword=None)])
        if not m.matches(left, type_call) and m.matches(right, type_call):
            left, right = right, left
        if not (
            m.matches(left, type_call)
            and isinstance(right, cst.Name)
            and right.value in _TYPE_PREDICATES
            and isinstance(
                target.operator, (cst.Is, cst.IsNot, cst.Equal, cst.NotEqual)
            )
        ):
            return updated_node
        AddImportsVisitor.add_needed_import(self.context, "types")
        check = cst.Call(
            func=cst.Attribute(
                cst.Name("types"), cst.Name(_TYPE_PREDICATES[right.value])
            ),
            args=[left.args[0].with_changes(comma=cst.MaybeSentinel.DEFAULT)],
        )
        if isinstance(target.operator, (cst.IsNot, cst.NotEqual)):
            return cst.UnaryOperation(
                operator=cst.Not(),
                expression=check,
                lpar=updated_node.lpar,
                rpar=updated_node.rpar,
            )
        return check.with_changes(lpar=updated_node.lpar, rpar=updated_node.rpar)


    # types.star currently has...
    def leave_Call(
        self, original_node: "Call", updated_node: "Call"
    ) -> "BaseExpression":
        AddImportsVisitor.add_needed_import(
            self.context,
            "larky",
            "larky",
        )
        if m.matches(updated_node, m.Call(func=m.Name("isinstance"))):
            AddImportsVisitor.add_needed_import(
                self.context,
                "builtins",
                "builtins",
            )
            # types.is_instance(...)
            #
            return updated_node.with_changes(
                func=Attribute(value=Name("builtins"), attr=Name("isinstance"))
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
