import logging
from collections import defaultdict
from typing import Dict, Set, Union

import libcst as cst
import libcst.matchers as m
from importanize import utils as importutils

# from libcst.codemod.visitors import AddImportsVisitor
from libcst.helpers import get_full_name_for_node

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


# check AddImportsVisitor
# # from libcst.codemod.visitors import AddImportsVisitor
class RewriteImports(cst.CSTTransformer):

    FUTURE_IMPORT = "__future__"

    def __init__(self, allowed=None):
        super(RewriteImports, self).__init__()
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

    def leave_import_alike(
        self,
        original_node: Union[cst.Import, cst.ImportFrom],
        updated_node: Union[cst.Import, cst.ImportFrom],
    ) -> Union[
        cst.Import, cst.ImportFrom, cst.RemovalSentinel, cst.FlattenSentinel
    ]:

        mod_name = None
        if type(updated_node) == cst.ImportFrom:
            mod_name = get_full_name_for_node(updated_node.module)
        elif type(updated_node) == cst.Import:
            mod_name = updated_node.names[0].name.value

        ns = "stdlib" if importutils.is_std_lib(mod_name) else "vendor"
        pkg = f'"@{ns}//{mod_name.replace(".", "/")}"'

        args = [cst.Arg(value=cst.SimpleString(pkg))]

        try:
            self._transpile_to_larky_load_function(args, updated_node)
        except TypeError:
            if type(updated_node.names) != cst.ImportStar:
                raise

        loadfunc = cst.Call(func=cst.Name(value="load"), args=args)
        return cst.FlattenSentinel([cst.Expr(loadfunc)])

    @staticmethod
    def _transpile_to_larky_load_function(args, updated_node):
        for name in updated_node.names:
            asname = name.asname
            if asname is not None:
                name_value = asname.name.value
            else:
                name_value = name.name.value

            import_name = f'"{name_value}"'
            import_as = f"{name_value}"
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
