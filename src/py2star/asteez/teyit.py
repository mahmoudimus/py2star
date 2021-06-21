import argparse
import binascii
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable, List, Union

import libcst as cst
import libcst.codemod
import libcst.matchers as m
from libcst import (
    BaseStatement,
    FlattenSentinel,
    RemovalSentinel,
    With,
)

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


TEMPLATE_PATTERN = re.compile("[\1\2]|[^\1\2]+")


def fill_template(template, *args):
    parts = TEMPLATE_PATTERN.findall(template)
    kids = []
    for p in parts:
        if p == "":
            continue
        elif p in "\1\2\3\4\5":
            p = args[ord(p) - 1]
            p = p.with_changes(comma=None)  # strip trailing comma, if any.
            p = _codegen.code_for_node(p)
        kids.append(p)
    return "".join(kids)


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
    # print(args)
    # asserts.assert_fails(, f".*?{exc_cls.value.value}")
    invokable = _codegen.code_for_node(
        cst.Call(func=args[0].value, args=args[1:])
    )
    regex = f'".*?{exc_cls.value.value}"'
    return cst.parse_expression(
        f"asserts.assert_fails(lambda: {invokable}, {regex})"
    )


@arity(6)
def raises_regex_op(exc_cls, regex, *args):
    """
    self.assertRaisesRegex(
                ValueError, "invalid literal for.*XYZ'$", int, "XYZ"
            )

    asserts.assert_fails(lambda: int("XYZ"),
                         ".*?ValueError.*izznvalid literal for.*XYZ'$")

    """
    # print(args)
    # asserts.assert_fails(, f".*?{exc_cls.value.value}")
    invokable = _codegen.code_for_node(
        cst.Call(
            func=args[0].value,
            args=[
                a.with_changes(
                    whitespace_after_arg=cst.SimpleWhitespace(value="")
                )
                for a in args[1:]
            ],
        )
    )
    regex = f'".*?{exc_cls.value.value}.*{regex.value.evaluated_value}"'
    return cst.parse_expression(
        f"asserts.assert_fails(lambda: {invokable}, {regex})"
    )


@arity(3)
def dual_op(template, first, second, error_msg=None, op="is_not_none"):
    # TODO: add error_msg to assertpy
    kids = fill_template(template, first, second)
    return cst.parse_expression(f"asserts.assert_that({kids}).{op}()")


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
    "failUnlessEqual": partial(comp_op, "is_equal_to"),
    "assertNotEqual": partial(comp_op, "is_not_equal_to"),
    "failIfEqual": partial(comp_op, "is_not_equal_to"),
    "assertNotEquals": partial(comp_op, "is_not_equal_to"),
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
    "assertFalse": partial(unary_op, "is_false"),
    "assertIsNone": partial(unary_op, "is_none"),
    "assertIsNotNone": partial(unary_op, "is_not_none"),
    "assertTrue": partial(unary_op, "is_true"),
    "assert_": partial(unary_op, "is_true"),
    "failIf": partial(unary_op, "is_false"),
    "failUnless": partial(unary_op, "is_true"),
    # "exceptions" in larky do not exist but we have asserts.assert_fails...
    "assertRaises": partial(raises_op),
    # types ones
    "assertDictContainsSubset": partial(
        dual_op, "dict(\2, **\1) == \2", op="is_true"
    ),
    "assertItemsEqual": partial(
        dual_op, "sorted(\1) == sorted(\2)", op="is_true"
    ),
    "assertRegex": partial(dual_op, "re.search(\2, \1)"),
    "assertNotRegex": partial(
        dual_op, "not re.search(\2, \1)", op="is_false"
    ),  # new Py 3.2
    # "assertWarns": partial(raises_op, "asserts"),
    # "assertAlmostEquals": "assertAlmostEqual",
    # "assertNotAlmostEquals": "assertNotAlmostEqual",
    # "failIfAlmostEqual": "assertNotAlmostEqual",
    # "failUnlessAlmostEqual": "assertAlmostEqual",
    # "assertAlmostEqual": partial(almost_op, "==", "<"),
    # "assertNotAlmostEqual": partial(almost_op, "!=", ">"),
    "assertRaisesRegex": partial(raises_regex_op),
    "assertWarnsRegex": partial(raises_regex_op),  # this will fail, but w/e
    # 'assertLogs': -- not to be handled here, is an context handler only
}


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


class TestTransformer(cst.codemod.ContextAwareTransformer):
    METADATA_DEPENDENCIES = (cst.metadata.ParentNodeProvider,)
    matchers: List[Rewrite]

    def __init__(self, context):
        super(TestTransformer, self).__init__(context)
        self.matchers = _build_matchers()

    # specialize with statements later.
    @m.call_if_not_inside(m.With(m.DoNotCare()))
    @m.leave(
        m.Call(
            func=m.Attribute(
                value=m.Name("self"),
                attr=m.Name(value=m.MatchRegex("(assert|fail).*")),
            )
        )
    )
    def rewrite_asserts_not_in_with_context(
        self, original_node: "cst.Call", updated_node: "cst.Call"
    ) -> "cst.BaseExpression":
        call = original_node
        args = call.args
        for match in self.matchers:
            if not m.matches(call, match.matcher):
                continue
            # if len(args) != match.arity:
            #     continue
            _args = args  # [args[i] for i in range(match.arity)]
            return match.replacement(*_args)

        return updated_node

    # specialize with statements later.
    # @m.call_if_inside(m.With(m.DoNotCare()))
    # @m.leave(
    #     m.With(
    #         items=[
    #             m.AtLeastN(
    #                 n=1,
    #                 matcher=m.WithItem(
    #                     item=m.Call(
    #                         func=m.Attribute(
    #                             value=m.Name("self"),
    #                             attr=m.Name(value=m.MatchRegex("assert.*")),
    #                         )
    #                     )
    #                 ),
    #             )
    #         ]
    #     )
    # )
    def leave_With(
        self, original_node: "With", updated_node: "With"
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        query = m.With(
            items=[
                m.AtLeastN(
                    n=1,
                    matcher=m.WithItem(
                        item=m.Call(
                            func=m.Attribute(
                                value=m.Name("self"),
                                attr=m.Name(value=m.MatchRegex("assert.*")),
                            )
                        )
                    ),
                )
            ]
        )
        if not m.matches(original_node, query):
            # print(">>>>> ", updated_node)
            return updated_node
        # gp.body.body[0].with_changes(trailing_whitespace=cst.TrailingWhitespace(newline=cst.Newline(value='')))
        func = cst.FunctionDef(
            name=cst.Name(_rand()),
            params=cst.Parameters(),
            body=updated_node.body,
        )
        # if regex:
        #     xxxx
        # else:
        #     xxxx
        assert_stmt = raises_op(
            updated_node.items[0].item.args[0], cst.Arg(value=func.name)
        )
        # p = self.get_metadata(cst.metadata.ParentNodeProvider, original_node)
        # if not isinstance(p, cst.FunctionDef):
        #     # no idea.. what to do? parent isn't a function!
        #     return updated_node
        # var = p.body
        # var.deep_replace(updated_node, )
        # p.deep_replace(updated_node, )
        return cst.FlattenSentinel(
            [
                func,
                cst.SimpleStatementLine(
                    body=[cst.Expr(value=assert_stmt)],
                    leading_lines=updated_node.leading_lines,
                ),
            ]
        )
        # return updated_node

    # def rewrite_asserts_in_with_conteaxt(
    #     self, original: "cst.Call", updated: "cst.Call"
    # ) -> "cst.BaseExpression":
    #     node = self.get_metadata(cst.metadata.ParentNodeProvider, original)
    #     while not isinstance(node, cst.With):
    #         node = self.get_metadata(cst.metadata.ParentNodeProvider, node)
    #     gp = cst.ensure_type(node, cst.With)
    #     # grandparent = self.get_metadata(cst.metadata.ParentNodeProvider, gp)
    #     # _codegen.code_for_node(gp.body.body[0].with_changes(trailing_whitespace=cst.TrailingWhitespace(newline=cst.Newline(value=''))))
    #     print("GOT HERE?")
    #     print(gp)
    #     # exception = updated.args[0].value.value
    #     # with self.assertRaises(TypeError):
    #     #     s.split(2)
    #     # self.assertRaises(lambda: s.split(2), ".*?TypeError")
    #
    #     # gp = gp.deep_replace(
    #     #     gp,
    #     #     cst.FunctionDef(
    #     #         name=cst.Name("_larky_xxx"),
    #     #         params=cst.Parameters(),
    #     #         body=gp.body,
    #     #     ),
    #     # )
    #     # print(_codegen.code_for_node(gp))
    #     # return gp
    #     return updated


def _rand():
    return f"_larky_{binascii.crc32(uuid.uuid4().bytes)}"


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
        # context = cst.codemod.CodemodContext()
        # rewriter = _AssertRewriter(context=context, blacklist=blacklist)
        # rewriter = TestTransformer()
        # tree = tree.visit(rewriter)
        mod = cst.MetadataWrapper(tree)
        ctx = cst.codemod.CodemodContext(wrapper=mod)
        transformer = TestTransformer(ctx)
        modified_tree = mod.visit(transformer)
        # modified_tree = tree.visit(transformer)
        return modified_tree.code


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
