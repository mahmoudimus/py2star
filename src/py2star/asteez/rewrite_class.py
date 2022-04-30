import argparse
import itertools
import typing

import libcst as cst
from libcst import codemod, ensure_type
from libcst import matchers as m
from libcst.codemod import CodemodContext
from libcst.metadata import ScopeProvider, ClassScope


# class ClassToFunctionRewriter(cst.CSTTransformer):


class ClassToFunctionRewriter(codemod.ContextAwareTransformer):

    DESCRIPTION = "Rewrites classes to functions"
    METADATA_DEPENDENCIES = (ScopeProvider,)

    @staticmethod
    def add_args(arg_parser: argparse.ArgumentParser) -> None:
        # Add command-line args that a user can specify for running this
        # codemod.
        arg_parser.add_argument(
            "--namespace-defs",
            dest="namespace_defs",
            help="namespace functions to their outer classes",
            default=False,
            action="store_true",
        )
        arg_parser.add_argument(
            "--remove-decorators",
            dest="remove_decorators",
            help="remove decorators",
            default=False,
            action="store_true",
        )
        arg_parser.add_argument(
            "--use-mutablestruct",
            dest="use_mutablestruct",
            help="Uses mutablestruct instead of types.new_class for class translation",
            default=False,
            action="store_true",
        )

    def __init__(
        self,
        context,
        namespace_defs=False,
        remove_decorators=False,
        use_mutablestruct=False,
    ) -> None:
        super(ClassToFunctionRewriter, self).__init__(context)
        self.namespace_defs = namespace_defs
        self.remove_decorators = remove_decorators
        self.use_mutablestruct = use_mutablestruct
        self.stack = []
        # self.parent_class = None
        # self.init_params = None
        # self.ns = []

    @property
    def parent_class(self):
        return self.stack[-1]["parent_class"] if self.stack else None

    @property
    def class_name(self):
        if not self.parent_class:
            return
        return self.parent_class.name.value

    @property
    def class_bases(self):
        if not self.parent_class:
            return ()
        return self.parent_class.bases

    @property
    def class_kwds(self):
        if not self.parent_class:
            return {}
        return self.parent_class.keywords

    @property
    def ns(self):
        return self.stack[-1]["ns"] if self.stack else None

    @property
    def init_params(self):
        return self.stack[-1]["init_params"] if self.stack else None

    @init_params.setter
    def init_params(self, val):
        self.stack[-1]["init_params"] = val

    def visit_ClassDef(self, node: cst.ClassDef) -> typing.Optional[bool]:
        self.stack.append(
            {
                "parent_class": node,
                "init_params": None,
                "ns": [],
            }
        )
        return True

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        scope = self.get_metadata(ScopeProvider, original_node)
        if isinstance(scope, ClassScope):
            for t in original_node.targets:
                self.ns.append(t.target.value)
        return updated_node

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        if not self.class_name:
            return updated_node
        if self.use_mutablestruct:
            return self.with_mutablestruct(original_node, updated_node)
        # Ok, we are using types so:
        #
        # class Foo(object):
        #     S = []
        #
        #     def __init__(self, foo, value):
        #         self.foo = foo
        #         self.value = value
        #
        #     @staticmethod
        #     def f():
        #         return True
        #
        #     @classmethod
        #     def cm(cls):
        #         return cls
        #
        # Becomes to:
        #
        # def _class_Foo():
        #     S = []
        #
        #     def __init__(self, foo, value):
        #         self.foo = foo
        #         self.value = value
        #
        #     def f():
        #         return True
        #     f = staticmethod(f)
        #
        #     def cm(cls):
        #         return cls
        #     cm = classmethod(cm)
        #
        #     __ns = {
        #         '__init__': __init__,
        #         'f': f,
        #         'cm': cm,
        #         'S': S
        #     }
        #     return types.new_class('Foo', (object,), {}, lambda x: x.update(__ns))
        # Foo = _class_Foo()

        self.ns.append(updated_node.name.value)
        return updated_node

    def with_mutablestruct(
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
        stripper = FunctionParameterStripper(self.context, ["self"])
        updated_node = updated_node.visit(stripper)
        updated_node = updated_node.visit(UndecorateClassMethods(self.context))

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
            params = self._remove_default_values(updated_node.params)
            (
                before,
                updated_node,
                self_func_assign,
            ) = self._emulate_class_construction(updated_node)
            prefixer = PrefixMethodByClsName(
                self.context, self.class_name, excluded_methods=("__init__",)
            )
            updated_node = updated_node.visit(prefixer)
        else:
            params = updated_node.params
            before, self_func_assign = self._assign_func_to_self(updated_node)
            if self.namespace_defs:
                prefixer = PrefixMethodByClsName(self.context, self.class_name)
                updated_node = updated_node.visit(prefixer)

        results: typing.List[typing.Any] = [before] if before else []

        n = updated_node.with_changes(
            # name=self._namespace_function_name(updated_node),
            params=params,
        )
        results.append(n)
        if self.class_name:
            results.append(self_func_assign)

        return cst.FlattenSentinel(results)

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
        return None, cst.SimpleStatementLine(body=[self_func_assign])

    def _emulate_class_construction(self, updated_node: cst.FunctionDef):
        func_name = updated_node.name.value
        args = []
        for p in itertools.chain(
            updated_node.params.params,
            updated_node.params.posonly_params,
            updated_node.params.kwonly_params,
            (updated_node.params.star_kwarg,),
        ):
            if not p:
                continue
            args.append(cst.Arg(value=p.name))
        # self = larky.mutablestruct(__name__='xxxx', __class__=xxxx)
        before = cst.SimpleStatementLine(
            body=[
                cst.Assign(
                    targets=[
                        cst.AssignTarget(
                            target=cst.Name(value="self"),
                            whitespace_before_equal=cst.SimpleWhitespace(
                                value=" "
                            ),
                            whitespace_after_equal=cst.SimpleWhitespace(
                                value=" "
                            ),
                        )
                    ],
                    value=cst.Call(
                        func=cst.Attribute(
                            value=cst.Name(value="larky"),
                            attr=cst.Name(value="mutablestruct"),
                        ),
                        args=[
                            cst.Arg(
                                value=cst.SimpleString(
                                    value=f"'{self.class_name}'"
                                ),
                                keyword=cst.Name(value="__name__"),
                                equal=cst.AssignEqual(
                                    whitespace_before=cst.SimpleWhitespace(
                                        value="",
                                    ),
                                    whitespace_after=cst.SimpleWhitespace(
                                        value="",
                                    ),
                                ),
                            ),
                            cst.Arg(
                                value=self.parent_class.name,
                                keyword=cst.Name(value="__class__"),
                                equal=cst.AssignEqual(
                                    whitespace_before=cst.SimpleWhitespace(
                                        value="",
                                    ),
                                    whitespace_after=cst.SimpleWhitespace(
                                        value="",
                                    ),
                                ),
                            ),
                        ],
                    ),
                )
            ]
        )
        # def __init__():
        #     return self  <-- insert this.
        body: cst.BaseSuite = updated_node.body
        body = body.with_changes(
            body=[
                *updated_node.body.body,
                cst.SimpleStatementLine(
                    body=[cst.Return(value=cst.Name(value="self"))]
                ),
            ]
        )
        # XXX: todo, what about pass?
        updated_node = updated_node.with_changes(body=body)
        # self = __init__(**kwargs)
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

        return (
            before,
            updated_node,
            cst.SimpleStatementLine(body=[self_func_assign]),
        )

    # def _namespace_function_name(self, node):
    #     """
    #     Rewrite function name to be namespaced with the classname, if
    #     namespace_defs flag is turned on.
    #
    #         class Foo(object):
    #            def __init__(self):
    #                pass
    #
    #     becomes:
    #
    #         class Foo(object):
    #            def Foo__init__(self):
    #                pass
    #     :param node:
    #     :return:
    #     """
    #     if self.namespace_defs:
    #         return cst.Name(f"{self.class_name}_{node.name.value}")
    #     return node.name

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
        params = cst.Parameters()
        if self.init_params:
            params = self.init_params
            # TODO (mahmoudimus): I have to fix this for the failing test
            # params = params.with_changes(star_arg=None)
        # params = params.deep_replace(
        #     params, params.with_changes(star_arg=cst.MaybeSentinel.DEFAULT)
        # )
        if self.use_mutablestruct:
            body = self.append_return_self_to_body(updated_node)
        else:
            body = self.create_dynamic_class(updated_node)
        # must clear out the parent class for future runs
        new_name = updated_node.name.value
        if not self.use_mutablestruct:
            new_name = "_class_" + new_name
        result = updated_node.deep_replace(
            updated_node,
            cst.FunctionDef(
                name=cst.Name(value=new_name),
                params=params,
                body=body,
            ),
        )
        self.stack.pop()
        if self.use_mutablestruct:
            return result
        return cst.FlattenSentinel(
            [
                result,
                cst.parse_statement(
                    f"{original_node.name.value} = {new_name}()"
                ),
            ]
        )

    def create_dynamic_class(self, updated_node):
        _template = (
            "types.new_class('{0}', ({1}), {{{2}}}, lambda x: x.update(__ns))"
        )
        block: cst.IndentedBlock = updated_node.body

        new_body = list(block.body)
        new_body.append(
            #     __ns = {
            #         '__init__': __init__,
            #         'f': f,
            #         'cm': cm
            #     }
            cst.parse_statement(
                "__ns = {\n"
                + "".join(f"    '{n}': {n},\n" for n in self.ns)
                + "}"
            )
        )
        new_body.append(
            cst.SimpleStatementLine(
                body=[
                    cst.Return(
                        value=cst.parse_expression(
                            _template.format(
                                self.class_name,
                                ",".join(
                                    self._base(b) for b in self.class_bases
                                ),
                                ",".join(
                                    f"{k.value.value}={k.keyword.value}"
                                    for k in self.class_kwds
                                ),
                            )
                        ),
                        whitespace_after_return=cst.SimpleWhitespace(value=" "),
                    ),
                ]
            )
        )
        return cst.IndentedBlock(
            body=new_body,
            footer=block.footer,
            header=block.header,
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

    @staticmethod
    def _remove_default_values(params: cst.Parameters):
        updated = []
        for p in itertools.chain(
            params.params,
            params.posonly_params,
            params.kwonly_params,
            (params.star_kwarg,),
        ):
            if not p:
                continue
            # if there's a default value for a parameter, remove it.
            if p.default is not None and p.equal != cst.MaybeSentinel:
                p = p.with_deep_changes(
                    p, default=None, equal=cst.MaybeSentinel
                )
            # __init__(x, y, **z)
            if p.star is not None:
                p = p.with_deep_changes(p, star=None)
            updated.append(p)
        return cst.Parameters(updated)

    def _base(self, b):
        if m.matches(b.value, m.Attribute()):
            parent = ensure_type(
                ensure_type(b.value, cst.Attribute).value, cst.Name
            ).value
            sub = ensure_type(
                ensure_type(b.value, cst.Attribute).attr, cst.Name
            ).value
            return f"{parent}.{sub}"
        else:
            return cst.ensure_type(b.value, cst.Name).value


class PrefixMethodByClsName(codemod.ContextAwareTransformer):
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
    """

    def __init__(self, context, class_name, excluded_methods=None) -> None:
        super(PrefixMethodByClsName, self).__init__(context)
        self.class_name = class_name
        self.excluded = excluded_methods if excluded_methods else ()

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        if updated_node.name.value in self.excluded:
            return updated_node
        if not self.class_name:
            return updated_node
        return updated_node.with_changes(
            name=cst.Name(f"{self.class_name}_{updated_node.name.value}"),
        )


class UndecorateClassMethods(codemod.ContextAwareTransformer):
    def __init__(self, context, exclude_decorators=None, noop=False) -> None:
        super(UndecorateClassMethods, self).__init__(context)
        self.excluded = (
            exclude_decorators
            if exclude_decorators
            else ["staticmethod", "classmethod"]
        )
        self.noop = noop

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> typing.Union[
        cst.BaseStatement,
        cst.FlattenSentinel[cst.BaseStatement],
        cst.RemovalSentinel,
    ]:
        return updated_node.with_changes(
            decorators=self.undecorate_function(updated_node)
        )

    def undecorate_function(self, updated_node):
        if self.noop:
            return updated_node.decorators

        decorators = []
        for dec in updated_node.decorators:
            if dec.decorator.value in self.excluded:
                continue
        return decorators


class FunctionParameterStripper(codemod.ContextAwareTransformer):
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


class ClassInstanceVariableRemover(codemod.ContextAwareTransformer):
    DESCRIPTION = "AttributeGetter(ctx, ['self']): self.foo() => foo()"

    def __init__(self, context: CodemodContext, namespace: typing.List):
        super(ClassInstanceVariableRemover, self).__init__(context)
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
