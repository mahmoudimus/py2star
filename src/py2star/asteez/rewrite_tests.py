import binascii
import re
import uuid
import typing

from dataclasses import dataclass
from functools import partial

from typing import Callable, List, Union

import libcst as cst
import libcst.codemod
from libcst import codemod
from libcst.codemod import CodemodContext
import libcst.matchers as m
from libcst import (
    BaseStatement,
    FlattenSentinel,
    RemovalSentinel,
    With,
)
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor

from py2star.asteez.rewrite_class import (
    ClassInstanceVariableRemover,
    FunctionParameterStripper,
    PrefixMethodByClsName,
    UndecorateClassMethods,
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
    "assertRaisesRegex": partial(raises_regex_op),
    "assertWarnsRegex": partial(raises_regex_op),  # this will fail, but w/e
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


def _rand(seed=None):
    if not seed:
        seed = uuid.uuid4().bytes
    if isinstance(seed, str):
        seed = seed.encode("utf-8")
    return f"_larky_{binascii.crc32(seed)}"


class AssertStatementRewriter(cst.codemod.ContextAwareTransformer):
    """
    Converts unittest assert methods to larky asserts, i.e.:

    - self.assertEquals(xx, yy) => asserts.assert_that(xx).is_equal_to(yy)
    """

    METADATA_DEPENDENCIES = (cst.metadata.ParentNodeProvider,)
    matchers: List[Rewrite]

    def __init__(self, context):
        super(AssertStatementRewriter, self).__init__(context)
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

        AddImportsVisitor.add_needed_import(self.context, "asserts")
        return updated_node

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
            return updated_node
        # gp.body.body[0].with_changes(
        #         trailing_whitespace=cst.TrailingWhitespace(
        #                   newline=cst.Newline(value='')))
        func = cst.FunctionDef(
            name=cst.Name(_rand(_codegen.code_for_node(updated_node.body))),
            params=cst.Parameters(),
            body=updated_node.body,
        )
        method_name = updated_node.items[0].item.func.attr.value.lower()
        if "regex" in method_name:
            # updated_node.items[0].item.func
            assert_stmt = raises_regex_op(
                updated_node.items[0].item.args[0],
                updated_node.items[0].item.args[1],
                cst.Arg(value=func.name),
            )
        else:
            assert_stmt = raises_op(
                updated_node.items[0].item.args[0], cst.Arg(value=func.name)
            )
        return cst.FlattenSentinel(
            [
                func,
                cst.SimpleStatementLine(
                    body=[cst.Expr(value=assert_stmt)],
                    leading_lines=updated_node.leading_lines,
                ),
            ]
        )


class DedentModule(codemod.ContextAwareTransformer):
    def leave_Module(
        self, original_node: "cst.Module", updated_node: "cst.Module"
    ) -> "cst.Module":

        module_body = []
        for classdef in updated_node.body:
            indentedbody = typing.cast(cst.IndentedBlock, classdef.body)
            module_body.extend([*indentedbody.body])
            # module_body.append(deindented_body)

        return updated_node.with_changes(body=module_body)


class Unittest2Functions(codemod.ContextAwareTransformer):
    """
    For all functions in a class, this will:
    - Strip self from functions in classes => (def z(self) => def(z))
    - Strip class instance variables (self.foo => foo)
    - Prefix method with class name (class Foo: def bar().. => def Foo__bar())

    For entire module:
    - dedents it
    """

    def __init__(self, context: CodemodContext, class_name=None):
        super(Unittest2Functions, self).__init__(context)
        self.class_name = class_name

    def visit_ClassDef(self, node: cst.ClassDef) -> typing.Optional[bool]:
        self.class_name = node.name.value
        return True

    # def leave_ClassDef(
    #     self, original_node: "cst.ClassDef", updated_node: "cst.ClassDef"
    # ) -> typing.Union[
    #     "cst.BaseStatement",
    #     cst.FlattenSentinel["cst.BaseStatement"],
    #     cst.RemovalSentinel,
    # ]:
    #     rewriter = ClassToFunctionRewriter(
    #         self.context, namespace_defs=True, remove_decorators=True
    #     )
    #     return updated_node.visit(rewriter)

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        un = updated_node.visit(
            FunctionParameterStripper(self.context, ["self"])
        )
        un = un.visit(ClassInstanceVariableRemover(self.context, ["self"]))
        un = un.visit(UndecorateClassMethods(self.context))
        un = un.visit(PrefixMethodByClsName(self.context, self.class_name))
        return un

    def leave_Module(
        self, original_node: "cst.Module", updated_node: "cst.Module"
    ) -> "cst.Module":
        # TestCase
        RemoveImportsVisitor.remove_unused_import(
            self.context, "unittest", asname="TestCase"
        )
        AddImportsVisitor.add_needed_import(self.context, "unittest")
        dedenter = DedentModule(self.context)
        return updated_node.visit(dedenter)
