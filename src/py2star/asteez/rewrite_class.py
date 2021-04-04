import libcst as ast
import libcst as cst
import typing

from libcst import codemod, matchers as m
from libcst.codemod import CodemodContext


class ClassToFunctionRewriter(cst.CSTTransformer):
    def __init__(self, namespace_defs=False):
        super(ClassToFunctionRewriter, self).__init__()
        self.namespace_defs = namespace_defs
        self.class_name = ""
        self.init_params = None

    def visit_ClassDef(self, node: cst.ClassDef) -> typing.Optional[bool]:
        self.class_name = node.name.value
        return True

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        # If there's an init, take its params to convert it
        # from:
        #
        # class Foo:
        #     def __init__(self, foo, value):
        #         pass
        #
        # to:
        #
        # def Foo(foo, value):
        #     def __init__(self, foo, value):
        #         pass
        #
        if updated_node.name.value == "__init__":
            self.init_params = FunctionParameterStripper.strip_function_params(
                updated_node.params, [m.Name("self")]
            )

        stripper = FunctionParameterStripper(CodemodContext(), ["self"])
        updated_node = updated_node.visit(stripper)

        return updated_node.with_changes(
            name=self.namespace_function_name(updated_node)
        )
        # if not self.namespace_defs:
        #     return updated_node
        #
        # return updated_node.with_changes(
        #     name=cst.Name(f"{self.class_name}_{updated_node.name.value}")
        # )

    def namespace_function_name(self, node):
        """
        Rewrite function name to be namespaced with the classname, if
        namespace_defs flag is turned on.

            class Foo(object):
               def __init__(self):
                   pass

        becomes:

            class Foo(object):
               def Foo__init__(self):
                   pass
        :param node:
        :return:
        """
        if self.namespace_defs:
            return cst.Name(f"{self.class_name}_{node.name.value}")
        return node.name

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        # params.with_changes(params=params)
        # params = cst.Parameters()
        params = (
            cst.Parameters(self.init_params)
            if self.init_params
            else cst.Parameters()
        )

        return updated_node.deep_replace(
            updated_node,
            cst.FunctionDef(
                name=updated_node.name,
                params=params,
                body=updated_node.body,  # XXX: add return self here
            ),
        )


class FunctionParameterStripper(codemod.VisitorBasedCodemodCommand):

    DESCRIPTION = "Strips configured params from function signatures"

    def __init__(self, context: CodemodContext, params: typing.List):
        super(FunctionParameterStripper, self).__init__(context)
        self.params = [m.Name(n) for n in params]

    def leave_FunctionDef(
        self, original_node: ast.FunctionDef, updated_node: ast.FunctionDef
    ) -> typing.Union[ast.BaseStatement, ast.RemovalSentinel]:
        params = self.strip_function_params(updated_node.params, self.params)
        return updated_node.with_changes(
            params=updated_node.params.with_changes(params=params)
        )

    @classmethod
    def strip_self(cls, context=None):
        """helper method to strip self from function parameters"""
        if not context:
            context = CodemodContext()
        return cls(context, ["self"])

    @staticmethod
    def strip_function_params(node_params, params):
        if not params:
            return node_params
        if isinstance(params[0], str):
            # if we passed in str params, then transform to m.Name()
            params = [m.Name(n) for n in params]

        modified_params = []
        for param in node_params.params:
            if m.matches(param, m.Param(name=m.OneOf(*params))):
                continue
            modified_params.append(param)
        return modified_params


class AttributeGetter(codemod.VisitorBasedCodemodCommand):

    DESCRIPTION = "AttributeGetter(ctx, ['self']): self.foo() => foo()"

    def __init__(self, context: CodemodContext, namespace: typing.List):
        super(AttributeGetter, self).__init__(context)
        self.namespace = [m.Name(n) for n in namespace]

    def leave_Attribute(
        self, original_node: ast.Attribute, updated_node: ast.Attribute
    ) -> typing.Union[ast.Attribute, ast.RemovalSentinel]:
        if m.matches(updated_node, m.Attribute(value=m.OneOf(*self.namespace))):
            return updated_node.with_changes(
                value=updated_node.attr,
                attr=ast.SimpleWhitespace(value=""),
                dot=ast.SimpleWhitespace(value=""),
            )
        return updated_node
