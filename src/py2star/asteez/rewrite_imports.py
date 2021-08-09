import dataclasses
import logging
import operator
import sys
import typing
from collections import defaultdict
from typing import Dict, Sequence, Set, Union, cast

import libcst as cst
import libcst.codemod
import libcst.matchers as m
from importanize import utils as importutils

# from libcst.codemod.visitors import AddImportsVisitor
from libcst import (
    BaseSmallStatement,
    Call,
    FlattenSentinel,
    RemovalSentinel,
    codemod,
)
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor
from libcst.helpers import get_full_name_for_node
from libcst.metadata import (
    FullyQualifiedNameProvider,
    ParentNodeProvider,
    QualifiedNameProvider,
)

logger = logging.getLogger(__name__)


def find_unused_imports(wrapper: cst.MetadataWrapper, warn_on_unused=False):
    log = logger.debug
    if warn_on_unused:
        log = logger.warning

    scopes = set(wrapper.resolve(cst.metadata.ScopeProvider).values())
    unused_imports: Dict[
        Union[cst.Import, cst.ImportFrom], Set[str]
    ] = defaultdict(set)
    undefined_references: Dict[cst.CSTNode, Set[str]] = defaultdict(set)
    ranges = wrapper.resolve(cst.metadata.PositionProvider)
    for scope in scopes:
        for assignment in scope.assignments:
            node = assignment.node
            if isinstance(assignment, cst.metadata.Assignment) and isinstance(
                node, (cst.Import, cst.ImportFrom)
            ):
                if len(assignment.references) == 0:
                    unused_imports[node].add(assignment.name)
                    location = ranges[node].start
                    log(
                        f"Warning on line {location.line:2d}, column {location.column:2d}: Imported name `{assignment.name}` is unused."
                    )

        for access in scope.accesses:
            if len(access.referents) == 0:
                node = access.node
                location = ranges[node].start
                log(
                    f"Warning on line {location.line:2d}, column {location.column:2d}: Name reference `{node.value}` is not defined."
                )
    return unused_imports, undefined_references


class RemoveUnusedImports(cst.CSTTransformer):
    """
    Invoke this like so:

        tree = cst.parse_module(dedent(".....code....here..."))
        wrapper = cst.metadata.MetadataWrapper(tree)
        unused_imports, undefined_refs = find_find_unused_imports(wrapper)
        rwi = rewrite_imports.RewriteImports(unused_imports)
        rewritten = wrapper.visit(rwi)
        rewritten.code # <- unused imports removed!

    """

    def __init__(
        self, unused_imports: Dict[Union[cst.Import, cst.ImportFrom], Set[str]]
    ) -> None:
        super().__init__()
        self.unused_imports = unused_imports

    def leave_import_alike(
        self,
        original_node: Union[cst.Import, cst.ImportFrom],
        updated_node: Union[cst.Import, cst.ImportFrom],
    ) -> Union[cst.Import, cst.ImportFrom, cst.RemovalSentinel]:
        if original_node not in self.unused_imports:
            return updated_node
        names_to_keep = []
        for name in updated_node.names:
            asname = name.asname
            if asname is not None:
                name_value = asname.name.value
            else:
                name_value = name.name.value
            if name_value not in self.unused_imports[original_node]:
                names_to_keep.append(
                    name.with_changes(comma=cst.MaybeSentinel.DEFAULT)
                )
        if len(names_to_keep) == 0:
            return cst.RemoveFromParent()
        else:
            return updated_node.with_changes(names=names_to_keep)

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> cst.Import:
        return self.leave_import_alike(original_node, updated_node)

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        return self.leave_import_alike(original_node, updated_node)


def in_stdlib_namespace(mod_name):
    if importutils.is_std_lib(mod_name):
        return True
    if mod_name.lower() in ("larky", "sets"):
        return True
    return False


# check AddImportsVisitor
# # from libcst.codemod.visitors import AddImportsVisitor
# class RewriteImports(cst.CSTTransformer):
# more here:
# https://github.com/Instagram/LibCST/blob/master/libcst/codemod/commands/rename.py
# https://github.com/hakancelik96/unimport/blob/master/unimport/refactor.py
# https://github.com/InvestmentSystems/pydelinter/blob/master/src/delinter/imports.py
class RewriteImports(codemod.ContextAwareTransformer):
    METADATA_DEPENDENCIES = (
        QualifiedNameProvider,
        ParentNodeProvider,
    )
    FUTURE_IMPORT = "__future__"

    def __init__(self, context=None, allowed=None):
        context = context if context else CodemodContext()
        super(RewriteImports, self).__init__(context)
        if not allowed:
            allowed = []
        self.allowed = allowed

    def remove_future_imports(
        self, updated_node: cst.ImportFrom
    ) -> Union[cst.ImportFrom, cst.RemovalSentinel]:
        names = list(
            filter(
                lambda x: not isinstance(x, cst.ImportAlias)
                or cst.ensure_type(x.name, cst.Name).value in self.allowed,
                updated_node.names,
            )
        )
        if names:
            return updated_node.with_changes(names=names)
        else:
            return cst.RemoveFromParent()

    @staticmethod
    def get_import_name_from_attr(attr_node: cst.Attribute) -> str:
        name = [attr_node.attr.value]  # last value
        node = attr_node.value
        while m.matches(node, m.OneOf(m.Name(), m.Attribute())):
            if isinstance(node, cst.Attribute):
                name.append(node.attr.value)
                node = node.value
            else:
                name.append(cst.ensure_type(node, cst.Name).value)
                break
        name.reverse()
        return ".".join(name)

    def leave_import_alike(
        self,
        original_node: Union[cst.Import, cst.ImportFrom],
        updated_node: Union[cst.Import, cst.ImportFrom],
    ) -> Union[
        cst.Import, cst.ImportFrom, cst.RemovalSentinel, cst.FlattenSentinel
    ]:
        # pp {qname.name
        #     for qnames in self.metadata[FullyQualifiedNameProvider].values()
        #     for qname in qnames
        #     if qname.source == (
        #       libcst.metadata.scope_provider.QualifiedNameSource.IMPORT)}
        #
        # ipdb> self.get_metadata(FullyQualifiedNameProvider, self.module)
        # {QualifiedName(name='jose.jwe', source=<QualifiedNameSource.LOCAL: 3>)}

        # /Users/mahmoud/src/unsorted/gelgel/python-jose/jose-larky/jwe.star
        # jose/backends/rsa_backend.py
        # https://github.com/MarcoGorelli/absolufy-imports
        # https://github.com/asottile/pyupgrade
        mod_name = None
        if type(updated_node) == cst.ImportFrom:
            mod_name = self._on_import_from(updated_node)
        elif type(updated_node) == cst.Import:
            assert (
                type(updated_node.names[0]) == cst.ImportAlias
            ), f"type(updated_node.names[0]) = {type(updated_node.names[0])}"
            import_attr: cst.Attribute = updated_node.names[0].name
            # import a.b.c
            if type(import_attr.value) == cst.Attribute:
                # let's re-write to from a.b import c
                _node = import_attr.value
                mod_name = f"{_node.value.value}.{_node.attr.value}"
            # import a.b as c
            elif type(import_attr.value) == cst.Name:
                mod_name = import_attr.value.value
            # import a as b
            else:
                mod_name = import_attr.value

        ns = "stdlib" if in_stdlib_namespace(mod_name) else "vendor"
        try:
            pkg = f'"@{ns}//{mod_name.replace(".", "/")}"'
        except AttributeError as e:
            # ipdb.set_trace()
            raise AttributeError(
                f"parent node: {updated_node.names} and child node: {mod_name}"
            ) from e

        args = [cst.Arg(value=cst.SimpleString(pkg))]

        try:
            self._compile_to_larky_load(args, updated_node)
        except TypeError:
            if type(updated_node.names) != cst.ImportStar:
                raise

        load_function = cst.Call(func=cst.Name(value="load"), args=args)
        return cst.FlattenSentinel([cst.Expr(load_function)])

    def _on_import_from(self, updated_node):
        module_attr = updated_node.module
        relative_imports = len(updated_node.relative)
        mod_name = ""
        if module_attr:
            mod_name = get_full_name_for_node(module_attr)
            if relative_imports == 0:
                return mod_name

        # we are a relative import!
        if self.context.full_module_name is None and mod_name:
            print(
                "attempting to rewrite relative import",
                mod_name,
                "with an unknown module name! trans-compilation will need to "
                "be run with -p command because root mod name is ambiguous..",
                file=sys.stderr,
            )
            name_root = ""
        else:
            # split the full module name to find out where we are
            paths = self.context.full_module_name.split(".")
            paths.reverse()
            # based on how many relative dots, we will make this an
            # absolute qualifier
            # ... jose.backends.pycrypto_backend
            # ... [pycrypto_backend, backends, jose]
            # ... [[pycrypto_backend, backends, jose][len(dots)]
            # ... from .base import Key => jose.backends.base
            # ... from ..utils import Y => jose.utils.Y
            name_root = ".".join(reversed(paths[relative_imports:]))
        # if len(updated_node.names) != 1:
        #     print(
        #         "updated_node.names != 1, will just pick first one",
        #         file=sys.stderr,
        #     )
        if mod_name:
            if name_root.endswith(".") and mod_name.startswith("."):
                name_root = name_root[:-1]
            elif not name_root.endswith(".") and not mod_name.startswith("."):
                name_root = name_root + "."
        else:
            if name_root.endswith("."):
                name_root = name_root[:-1]
        return f"{name_root}{mod_name}"

    @staticmethod
    def _compile_to_larky_load(args, updated_node):
        names = cast(Sequence[cst.ImportAlias], updated_node.names)
        for node_name in names:
            name = node_name.name
            if node_name.asname:
                name = node_name.asname.name

            if (
                type(name) == cst.Attribute
                and type(name.value) == cst.Attribute
            ):
                # import a.b.c => load("@{ns}//a/b", c="c")
                import_name = f'"{name.attr.value}"'
                import_as = f"{name.attr.value}"
            elif type(name) == cst.Attribute and type(name.value) == cst.Name:
                import_name = f'"{name.attr.value}"'
                import_as = f"{name.attr.value}"
            else:
                import_name = f'"{name.value}"'
                import_as = f"{name.value}"

            args.append(
                cst.Arg(
                    keyword=cst.Name(import_as),
                    value=cst.SimpleString(value=import_name),
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
                )
            )
        return args

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> cst.Import:
        return self.leave_import_alike(original_node, updated_node)

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        if m.matches(updated_node.module, m.Name(self.FUTURE_IMPORT)):
            return self.remove_future_imports(updated_node)
        return self.leave_import_alike(original_node, updated_node)

    # def leave_Call(
    #     self, original_node: cst.Call, updated_node: cst.Call
    # ) -> cst.Call:
    #     print(updated_node)
    #     if m.matches(updated_node, m.Call(func=m.Name("load"))):
    #         return self.leave_import_alike(original_node, updated_node)
    #     return updated_node


class RemoveDelKeyword(codemod.ContextAwareTransformer):
    METADATA_DEPENDENCIES = (
        cst.metadata.ParentNodeProvider,
        cst.metadata.ScopeProvider,
        cst.metadata.PositionProvider,
    )

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.names = []

    @m.call_if_inside(m.SimpleStatementLine(body=[m.Del(target=m.DoNotCare())]))
    def leave_SimpleStatementLine(
        self,
        original_node: "SimpleStatementLine",
        updated_node: "SimpleStatementLine",
    ) -> Union[
        "BaseStatement", FlattenSentinel["BaseStatement"], RemovalSentinel
    ]:
        # del self.xxxx
        _attr = m.Del(
            target=m.Tuple(
                elements=[
                    m.AtLeastN(
                        n=1,
                        matcher=m.Element(
                            value=m.Attribute(value=m.DoNotCare())
                        ),
                    )
                ]
            )
        )
        if updated_node.body and m.matches(updated_node.body[0], _attr):
            commented = "# del " + "".join(
                self.module.code_for_node(t)
                for t in updated_node.body[0].target.elements
            )
            un = updated_node.with_changes(
                body=[cst.Pass()],
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=cst.Comment(value=commented)),
                ],
            )
            return un
        # del a[b]
        _delitem = m.Del(
            target=m.Subscript(
                value=m.OneOf(
                    m.Name(value=m.DoNotCare()),
                    m.Attribute(value=m.DoNotCare()),
                )
            )
        )
        if m.matches(updated_node.body[0], _delitem):
            # operator.delitem(a, b, /)
            # Same as del a[b].
            AddImportsVisitor.add_needed_import(self.context, "operator")
            un = updated_node.deep_replace(
                updated_node,
                cst.helpers.parse_template_statement(
                    # "operator.delitem({value}.{attr}, {slice})",
                    "operator.delitem({value}, {slice})",
                    config=self.module.config_for_parsing,
                    value=updated_node.body[0].target.value,
                    # attr=updated_node.target.value.attr,
                    slice=updated_node.body[0].target.slice[0].slice.value,
                ),
            )
            return un
        return updated_node


class LarkyImportSorter(codemod.ContextAwareTransformer):
    METADATA_DEPENDENCIES = (
        cst.metadata.ScopeProvider,
        cst.metadata.PositionProvider,
    )

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.names = set()

    def process_node(
        self,
        node: Union[
            cst.FunctionDef, cst.ClassDef, cst.BaseAssignTargetExpression
        ],
        name: str,
    ) -> None:
        scope = self.get_metadata(cst.metadata.ScopeProvider, node)
        if not isinstance(scope, cst.metadata.GlobalScope):
            return
        # we are in global scope
        if not name.startswith("_"):
            self.names.add(name)

    @m.call_if_inside(m.Call(func=m.Name(value="load")))
    def visit_Call(self, node: "Call") -> typing.Optional[bool]:
        self.names.add((node.args[0].value, node))
        return True

    @m.call_if_inside(m.Expr(value=m.Call(func=m.Name(value="load"))))
    def leave_Expr(
        self, original_node: "Expr", updated_node: "Expr"
    ) -> Union[
        "BaseSmallStatement",
        FlattenSentinel["BaseSmallStatement"],
        RemovalSentinel,
    ]:
        # must be top level scope!
        scope = self.get_metadata(cst.metadata.ScopeProvider, original_node)
        if not isinstance(scope, cst.metadata.GlobalScope):
            return updated_node
        return cst.RemoveFromParent()

    def leave_Module(
        self, original_node: libcst.Module, updated_node: libcst.Module
    ) -> libcst.Module:
        body = []
        if not updated_node.body:
            return updated_node
        i = 0
        statement = None
        for _i, _statement in enumerate(updated_node.body):
            i = _i
            statement = _statement
            # keep going until we hit a search
            if m.matches(
                statement,
                m.SimpleStatementLine(body=[m.Expr(value=m.SimpleString())]),
            ):
                body.append(statement)
            else:
                body.extend(
                    cst.SimpleStatementLine(body=[cst.Expr(value=y)])
                    # sort imports in lexicographic order
                    for x, y in sorted(self.names, key=lambda x: x[0].value)
                )
                break

        # check for leading lines (empty lines or comments) before
        # the next item in the body and move it above
        first_item = body[-len(self.names)]
        # copy the leading lines from the next statement
        # and put it on the last body item
        if (
            m.matches(statement, m.SimpleStatementLine())
            and statement.leading_lines
        ):
            first_item = first_item.with_changes(
                leading_lines=statement.leading_lines
            )
            statement = statement.with_changes(leading_lines=[cst.EmptyLine()])
            body[-len(self.names)] = first_item
        body.append(statement)

        if i + 1 < len(updated_node.body):
            body.extend(updated_node.body[i + 1 :])

        return updated_node.with_changes(body=body)
