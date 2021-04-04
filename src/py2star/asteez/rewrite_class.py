import typing

import libcst as cst
from libcst import codemod
from libcst import matchers as m
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

        # remove self from all functions
        # (IMPORTANT! Run self stripper FIRST to set functions w/o self so
        #  rewriting can use selfless parameters when manually setting
        #  functions).
        stripper = FunctionParameterStripper(CodemodContext(), ["self"])
        updated_node = updated_node.visit(stripper)

        # If there's an init, take its params to convert it
        # from:
        #
        # class Foo:
        #     def __init__(foo, value):
        #         pass
        #
        # to:
        #
        # def Foo(foo, value):
        #     def __init__(foo, value):
        #         pass
        #
        if updated_node.name.value == "__init__":
            # init is a special case
            # TODO: __new__ and metaclasses? not supported for now.
            self.init_params = updated_node.params
            self_func_assign = self._emulate_class_construction(updated_node)
        else:
            self_func_assign = self._assign_func_to_self(updated_node)

        return cst.FlattenSentinel(
            [
                updated_node.with_changes(
                    name=self._namespace_function_name(updated_node)
                ),
                cst.SimpleStatementLine(body=[self_func_assign]),
            ]
        )

    @staticmethod
    def _assign_func_to_self(updated_node: cst.FunctionDef):
        """
        add self.$func_name = $func_name at the end of the function
        so:
            def foo():
                def bar(x, y):
                    pass
        becomes:

            def foo():
                def bar(x, y):
                    pass
                self.bar = bar   <-- inserted
        """
        func_name = updated_node.name.value
        selfdot = cst.Attribute(
            value=cst.Name(value="self"),
            attr=cst.Name(value=f"{func_name}"),
            dot=cst.Dot(
                whitespace_before=cst.SimpleWhitespace(value=""),
                whitespace_after=cst.SimpleWhitespace(value=""),
            ),
        )

        self_func_assign = cst.Assign(
            targets=[
                cst.AssignTarget(
                    target=selfdot,
                    whitespace_before_equal=cst.SimpleWhitespace(value=" "),
                    whitespace_after_equal=cst.SimpleWhitespace(value=" "),
                )
            ],
            value=cst.Name(value=f"{func_name}"),
        )
        return self_func_assign

    @staticmethod
    def _emulate_class_construction(updated_node: cst.FunctionDef):
        func_name = updated_node.name.value
        args = []
        for p in updated_node.params.params:
            args.append(cst.Arg(value=p.name))
        self_func_assign = cst.Assign(
            targets=[
                cst.AssignTarget(
                    target=cst.Name(value="self"),
                    whitespace_before_equal=cst.SimpleWhitespace(value=" "),
                    whitespace_after_equal=cst.SimpleWhitespace(value=" "),
                )
            ],
            value=cst.Call(func=cst.Name(value=f"{func_name}"), args=args),
        )
        return self_func_assign

    def _namespace_function_name(self, node):
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
        # # params.with_changes(params=params)
        # # params = cst.Parameters()
        # params = (
        #     cst.Parameters(self.init_params)
        #     if self.init_params
        #     else cst.Parameters()
        # )
        params = self.init_params if self.init_params else cst.Parameters()
        body = self.append_return_self_to_body(updated_node)
        return updated_node.deep_replace(
            updated_node,
            cst.FunctionDef(
                name=updated_node.name,
                params=params,
                body=body,
            ),
        )

    @staticmethod
    def append_return_self_to_body(updated_node):
        """literally...adds return self to the end of the function body"""
        block: cst.IndentedBlock = updated_node.body
        new_body = list(block.body)
        new_body.append(
            cst.SimpleStatementLine(
                body=[
                    cst.Return(
                        value=cst.Name(value="self"),
                        whitespace_after_return=cst.SimpleWhitespace(value=" "),
                    )
                ]
            )
        )
        return cst.IndentedBlock(
            body=new_body,
            footer=block.footer,
            header=block.header,
        )


class FunctionParameterStripper(codemod.VisitorBasedCodemodCommand):
    DESCRIPTION = "Strips configured params from function signatures"

    def __init__(self, context: CodemodContext, params: typing.List):
        super(FunctionParameterStripper, self).__init__(context)
        self.params = [m.Name(n) for n in params]

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> typing.Union[cst.BaseStatement, cst.RemovalSentinel]:
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
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> typing.Union[cst.Attribute, cst.RemovalSentinel]:
        if m.matches(updated_node, m.Attribute(value=m.OneOf(*self.namespace))):
            return updated_node.with_changes(
                value=updated_node.attr,
                attr=cst.SimpleWhitespace(value=""),
                dot=cst.SimpleWhitespace(value=""),
            )
        return updated_node
