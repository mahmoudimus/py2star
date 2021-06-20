import argparse
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

import libcst as cst
import libcst.codemod
import libcst.matchers as m

OPERATOR_TABLE = {
    cst.Equal: "assertEqual",
    cst.NotEqual: "assertNotEqual",
    cst.LessThan: "assertLess",
    cst.LessThanEqual: "assertLessEqual",
    cst.GreaterThan: "assertGreater",
    cst.GreaterThanEqual: "assertGreaterEqual",
    cst.In: "assertIn",
    cst.NotIn: "assertNotIn",
    cst.Is: "assertIs",
    cst.IsNot: "assertIsNot",
}

CONTRA_OPS = {cst.Equal: cst.NotEqual, cst.In: cst.NotIn, cst.Is: cst.IsNot}

for key, value in CONTRA_OPS.copy().items():
    CONTRA_OPS[value] = key

DEPRECATED_ALIASES = {
    "assert_": "assertTrue",
    "failIf": "assertFalse",
    "failUnless": "assertTrue",
    "assertEquals": "assertEqual",
    "failIfEqual": "assertNotEqual",
    "failUnlessEqual": "assertEqual",
    "assertNotEquals": "assertNotEqual",
    "assertAlmostEquals": "assertAlmostEqual",
    "failIfAlmostEqual": "assertNotAlmostEqual",
    "failUnlessAlmostEqual": "assertAlmostEqual",
    "assertNotAlmostEquals": "assertNotAlmostEqual",
}


@dataclass
class Rewrite:
    matcher: m.Call
    arity: int
    replacement: Callable


class TestTransformer(m.MatcherDecoratableTransformer):
    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.BaseExpression
    ) -> cst.BaseExpression:

        call = original_node
        args = call.args

        matchers: List[Rewrite] = [
            # self.assertEqual(a,b) => assert a == b
            Rewrite(
                matcher=m.Call(
                    func=m.Attribute(
                        value=m.Name("self"), attr=m.Name("assertEqual")
                    )
                ),
                arity=2,
                replacement=lambda: cst.Assert(
                    cst.Comparison(
                        args[0].value,
                        [cst.ComparisonTarget(cst.Equal(), args[1].value)],
                    )
                ),
            ),
            # self.assertNotEqual(a,b) => assert a != b
            Rewrite(
                m.Call(
                    func=m.Attribute(
                        value=m.Name("self"), attr=m.Name("assertNotEqual")
                    )
                ),
                2,
                lambda: cst.Assert(
                    cst.Comparison(
                        args[0].value,
                        [cst.ComparisonTarget(cst.NotEqual(), args[1].value)],
                    )
                ),
            ),
            # self.assertTrue(a) => assert a
            Rewrite(
                m.Call(
                    func=m.Attribute(
                        value=m.Name("self"), attr=m.Name("assertTrue")
                    )
                ),
                1,
                lambda: cst.Assert(args[0].value),
            ),
            # self.assertIsNone(a) => assert a is None
            Rewrite(
                m.Call(
                    func=m.Attribute(
                        value=m.Name("self"), attr=m.Name("assertIsNone")
                    )
                ),
                1,
                lambda: cst.Assert(
                    cst.Comparison(
                        args[0].value,
                        [cst.ComparisonTarget(cst.Is(), cst.Name("None"))],
                    )
                ),
            ),
            # self.assertIsNotNone(a) => assert a is not None
            Rewrite(
                m.Call(
                    func=m.Attribute(
                        value=m.Name("self"), attr=m.Name("assertIsNotNone")
                    )
                ),
                1,
                lambda: cst.Assert(
                    cst.Comparison(
                        args[0].value,
                        [
                            cst.ComparisonTarget(
                                cst.Is(), cst.parse_expression("not None")
                            )
                        ],
                    )
                ),
            ),
        ]

        for match in matchers:
            if m.matches(call, match.matcher):
                if len(args) == match.arity:
                    return match.replacement()

        return updated_node


def rewrite_module(code: str) -> str:
    tree = cst.parse_module(code)

    transformer = TestTransformer()
    modified_tree = tree.visit(transformer)

    return modified_tree.code


class _AssertRewriter(libcst.codemod.ContextAwareTransformer):
    def __init__(self, context, blacklist=frozenset(), *args, **kwargs):
        super(_AssertRewriter, self).__init__(context)
        self.asserts = []
        self.blacklist = blacklist

    @m.call_if_inside(
        m.Call(
            func=m.Attribute(
                value=m.Name("self"),
                attr=m.Name(value=m.MatchRegex("assert.*")),
            ),
            args=[m.AtLeastN(n=1, matcher=m.Arg())],
        )
    )
    def leave_Call(
        self, original_node: "cst.Call", updated_node: "cst.Call"
    ) -> "cst.BaseExpression":
        if not m.matches(updated_node.func.value, m.Name(value="self")):
            return updated_node

        visitor_proc = f"visit_{updated_node.func.attr.name.value}"
        with suppress(Exception):
            if updated_node.func.attr.name.value in DEPRECATED_ALIASES:
                self.asserts.append(
                    updated_node
                    # Rewrite(
                    #     updated_node,
                    #     DEPRECATED_ALIASES[updated_node.func.attr],
                    #     updated_node.args,
                    # )
                )
            elif not hasattr(self, visitor_proc):
                print("")
                return updated_node
            elif rewrite := getattr(self, visitor_proc)(updated_node):
                self.asserts.append(rewrite)
        return updated_node

    def visit_assertTrue(self, node, positive=True):
        print("self.assertTrue: ", node)
        # expr, *args = node.args
        # if isinstance(expr, cst.Compare) and len(expr.ops) == 1:
        #     left = expr.left
        #     operator = type(expr.ops[0])
        #     if not positive:
        #         if operator in CONTRA_OPS:
        #             operator = CONTRA_OPS[operator]
        #         else:
        #             return None
        #
        #     (comparator,) = expr.comparators
        #     if (
        #         operator in (cst.Is, cst.IsNot)
        #         and isinstance(comparator, cst.Constant)
        #         and comparator.value is None
        #     ):
        #
        #         func = f"assert{operator.__name__}None"
        #         args = [left, *args]
        #     elif operator in OPERATOR_TABLE:
        #         func = OPERATOR_TABLE[operator]
        #         args = [left, comparator, *args]
        #     else:
        #         return None
        # elif (
        #     isinstance(expr, cst.Call)
        #     and cst.unparse(expr.func) == "isinstance"
        #     and len(expr.args) == 2
        # ):
        #     if positive:
        #         func = "assertIsInstance"
        #     else:
        #         func = "assertNotIsInstance"
        #     args = [*expr.args, *args]
        # else:
        #     return None
        # return Rewrite(node, func, args)

    def visit_assertFalse(self, node):
        return self.visit_assertTrue(node, positive=False)

    def visit_assertIs(self, node, positive=True):
        left, right, *args = node.args
        if isinstance(right, cst.Constant):
            if (
                right.value in (True, False)
                and isinstance(right.value, bool)
                and positive
            ):
                func = f"assert{right.value}"
            elif right.value is None:
                if positive:
                    func = "assertIsNone"
                else:
                    func = "assertIsNotNone"
            args = [left, *args]
        else:
            return None
        return Rewrite(node, func, args)

    def visit_assertIsNot(self, node):
        return self.visit_assertIs(node, positive=False)


def rewrite_source(source, *, blacklist=frozenset()):
    if not source:
        return source

    with open(source, "rb") as f:
        tree = cst.parse_module(f.read())
        context = cst.codemod.CodemodContext()
        # rewriter = _AssertRewriter(context=context, blacklist=blacklist)
        rewriter = TestTransformer()
        tree = tree.visit(rewriter)
        return tree.code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=Path)
    parser.add_argument(
        "--pattern",
        default="test_*.py",
        help="Wildcard pattern for capturing test files.",
    )
    parser.add_argument(
        "--show-stats",
        action="store_true",
        help="Print out some debug stats related about refactorings",
    )
    parser.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Exit with status code 1 if any file changed",
    )
    options = parser.parse_args()
    print(rewrite_source(options.filename))


if __name__ == "__main__":
    main()
