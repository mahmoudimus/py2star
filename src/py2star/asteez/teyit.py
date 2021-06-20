import argparse
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable, List, Tuple
import re


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


_codegen = cst.parse_module("")


def arity(n):
    def f(func):
        func.arity = n
        return func

    return f


@arity(2)
def comp_op(op, lefty, righty):
    left = _codegen.code_for_node(lefty.value)
    right = _codegen.code_for_node(righty.value)
    return cst.parse_expression(f"asserts.assert_that({left}).{op}({right})")


@arity(1)
def unary_op(op, suty):
    """/Users/mahmoud/src/py-in-java/pycryptodome/lib/transform.py
    /Users/mahmoud/src/py2star/transform1.py
    Converts a method like: ``self.failUnless(True)`` to
      asserts.assert_that(value).is_true()
    """
    sut = _codegen.code_for_node(suty.value)
    return cst.parse_expression(f"asserts.assert_that({sut}).{op}()")


@arity(5)
def raises_op(exc_cls, *args):
    """
    assertRaises(exception, callable, *args, **kwds)
    assertRaises(exception, *, msg=None)

    # Test that an exception is raised when callable is called with any
    # positional or keyword arguments that are also passed to
    # assertRaises().

    asserts.assert_fails(lambda: -1 in b("abc"), "-1 not in range")

    """
    print(args)
    invokable = "lambda x: x"
    regex = '".*"'
    return cst.parse_expression(f"asserts.assert_fails({invokable}, {regex})")


@arity(5)
def regex_op(exc_cls, *args):
    """
    assertRaises(exception, callable, *args, **kwds)
    assertRaises(exception, *, msg=None)

    # Test that an exception is raised when callable is called with any
    # positional or keyword arguments that are also passed to
    # assertRaises().

    asserts.assert_fails(lambda: -1 in b("abc"), "-1 not in range")

    """
    print(args)
    invokable = lambda x: x
    regex = ".*"
    return cst.parse_expression(f"asserts.assert_fails({invokable}, {regex})")


# def raises_op(context, exceptionClass, indent, kws, arglist, node):
#     # asserts.assert_fails(lambda: -1 in b("abc"), "int in bytes: -1 out of range")
#     exceptionClass.prefix = ""
#     args = [
#         String('"', prefix=" "),  # unquoted on purpose
#         String(".*?"),  # match anything until the exception we are looking for
#         String(f"{str(exceptionClass)}"),
#     ]
#     # this would be the second parameter
#     # Add match keyword arg to with statement if an expected regex was provided.
#     if "expected_regex" in kws:
#         expected_regex = kws.get("expected_regex").clone()
#         expected_regex.prefix = ""
#         args.append(String(".*"))
#         args.append(expected_regex)
#     args.append(String('"'))  # close quote
#
#     # # assertRaises(exception, callable, *args, **kwds)
#     # # assertRaises(exception, *, msg=None)
#     # # Test that an exception is raised when callable is called with any
#     # # positional or keyword arguments that are also passed to
#     # # assertRaises().
#     # # To catch any of a group of exceptions, a tuple containing the
#     # # exception classes may be passed as exception.
#     # with_item = Call(Name(context), args) # pytest.raises(TypeError)
#     # with_item.prefix = " "
#     # args = []
#     arglist = [a.clone() for a in arglist.children[4:]]
#     if arglist:
#         arglist[0].prefix = ""
#
#     func = None
#
#     # :fixme: this uses hardcoded parameter names, which may change
#     if "callableObj" in kws:
#         func = kws["callableObj"]
#     elif "callable_obj" in kws:
#         func = kws["callable_obj"]
#     elif kws["args"]:  # any arguments assigned to `*args`
#         func = kws["args"][0]
#     else:
#         func = None
#
#     if func and func.type == syms.lambdef:
#         suite = func.children[-1].clone()
#     else:
#         if func is None:
#             # Context manager, so let us convert it to a function definition
#             # let us create a function first.
#             func = get_funcdef_node(
#                 funcname=_rand(),
#                 args=[],
#                 body=arglist,
#                 decorators=[],
#                 indentation_level=1,
#             )
#             # append it as a child to the root node
#             find_root(node).append_child(func)
#             # return Node(syms.with_stmt, [with_item])
#         # TODO: Newlines within arguments are not handled yet.
#         # If argment prefix contains a newline, all whitespace around this
#         # ought to be replaced by indent plus 4+1+len(func) spaces.
#         suite = get_lambdef_node([Call(Name(str(func)), arglist)])
#
#     # suite.prefix = indent + (4 * " ")
#     # new = Node(
#     #     syms.power,
#     #     # trailer< '.' 'is_equal_to' > trailer< '(' '2' ')' > >
#     #     Attr(_left_asserts, Name(op))
#     #     + [Node(syms.trailer, [LParen(), right, RParen()])],
#     # )
#     return Call(
#         Name("assert_fails"),
#         args=[suite, Comma()] + args,
#     )
#     # return Node(
#     #     syms.with_stmt, [Name("with"), with_item, Name(":"), Newline(), suite]
#     # )


_method_map = {
    # simple equals
    # asserts.eq(A, B) || asserts.assert_that(A).is_equal_to(B)
    "assertDictEqual": partial(comp_op, "is_equal_to"),
    "assertListEqual": partial(comp_op, "is_equal_to"),
    "assertMultiLineEqual": partial(comp_op, "is_equal_to"),
    "assertSetEqual": partial(comp_op, "is_equal_to"),
    "assertTupleEqual": partial(comp_op, "is_equal_to"),
    "assertSequenceEqual": partial(comp_op, "is_equal_to"),
    "assertEqual": partial(comp_op, "is_equal_to"),
    "assertNotEqual": partial(comp_op, "is_not_equal_to"),
    "assertIs": partial(comp_op, "is_equal_to"),
    "assertGreater": partial(comp_op, "is_greater_than"),
    "assertLessEqual": partial(comp_op, "is_lte_to"),
    "assertLess": partial(comp_op, "is_less_than"),
    "assertGreaterEqual": partial(comp_op, "is_gte_to"),
    "assertIn": partial(comp_op, "is_in"),
    "assertIsNot": partial(comp_op, "is_not_equal_to"),
    "assertNotIn": partial(comp_op, "is_not_in"),
    "assertIsInstance": partial(comp_op, "is_instance_of"),
    "assertNotIsInstance": partial(comp_op, "is_not_instance_of"),
    # unary operations
    "assertIsNone": partial(unary_op, "is_none"),
    "assertIsNotNone": partial(unary_op, "is_not_none"),
    "assertFalse": partial(unary_op, "is_false"),
    "failIf": partial(unary_op, "is_false"),
    "assertTrue": partial(unary_op, "is_true"),
    "failUnless": partial(unary_op, "is_true"),
    "assert_": partial(unary_op, "is_true"),
    # "exceptions" in larky do not exist but we have asserts.assert_fails...
    "assertRaises": partial(raises_op, "asserts"),
    # "assertWarns": partial(raises_op, "asserts"),
    # # types ones
    # "assertDictContainsSubset": partial(dual_op, "dict(\2, **\1) == \2"),
    # "assertItemsEqual": partial(dual_op, "sorted(\1) == sorted(\2)"),
    "assertRegex": partial(dual_op, "re.search(\2, \1)"),
    # "assertNotRegex": partial(dual_op, "not re.search(\2, \1)"),  # new Py 3.2
    # "assertAlmostEqual": partial(almost_op, "==", "<"),
    # "assertNotAlmostEqual": partial(almost_op, "!=", ">"),
    # "assertRaisesRegex": partial(RaisesRegexOp, "pytest.raises", "excinfo"),
    # "assertWarnsRegex": partial(RaisesRegexOp, "pytest.warns", "record"),
    # 'assertLogs': -- not to be handled here, is an context handler only
}

TEMPLATE_PATTERN = re.compile("[\1\2]|[^\1\2]+")


# def fill_template(template, *args):
#     parts = TEMPLATE_PATTERN.findall(template)
#     kids = []
#     for p in parts:
#         if p == "":
#             continue
#         elif p in "\1\2\3\4\5":
#             p = args[ord(p) - 1]
#             p.prefix = ""
#         else:
#             p = cst.Name(p)
#         kids.append(p)
#     return kids
#
#
# def DualOp(template, first, second):
#     kids = fill_template(template, first, second)
#     return cst.Node(syms.test, kids, prefix=" ")


def _build_matchers() -> List[Rewrite]:
    return [
        # e.g. self.assertEqual(a,b) => assert a == b
        Rewrite(
            matcher=m.Call(
                func=m.Attribute(
                    # e.g. self.assertEqual
                    value=m.Name("self"),
                    attr=m.Name(unittest_method),
                )
            ),
            arity=replacement.func.arity,
            replacement=replacement,
        )
        for unittest_method, replacement in _method_map.items()
    ]


class TestTransformer(m.MatcherDecoratableTransformer):

    matchers: List[Rewrite]

    def __init__(self):
        super(TestTransformer, self).__init__()
        self.matchers = _build_matchers()

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.BaseExpression
    ) -> cst.BaseExpression:

        call = original_node
        args = call.args

        for match in self.matchers:
            if not m.matches(call, match.matcher):
                continue
            if len(args) != match.arity:
                continue
            _args = [args[i] for i in range(match.arity)]
            return match.replacement(*_args)

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
