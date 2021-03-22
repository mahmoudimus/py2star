import typing

import libcst as ast
import libcst.matchers as m
from libcst import codemod
from libcst.codemod import CodemodContext


class FunctionParameterStripper(codemod.VisitorBasedCodemodCommand):

    DESCRIPTION = "Strips configured params from function signatures"

    def __init__(self, context: CodemodContext, params: typing.List):
        super(FunctionParameterStripper, self).__init__(context)
        self.params = [m.Name(n) for n in params]

    def leave_FunctionDef(
        self, original_node: ast.FunctionDef, updated_node: ast.FunctionDef
    ) -> typing.Union[ast.BaseStatement, ast.RemovalSentinel]:
        modified_params = []
        for param in updated_node.params.params:
            if m.matches(param, m.Param(name=m.OneOf(*self.params))):
                continue
            modified_params.append(param)

        return updated_node.with_changes(
            params=updated_node.params.with_changes(params=modified_params)
        )


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
