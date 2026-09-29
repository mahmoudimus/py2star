"""
The larkify pipeline: ordered libcst passes that rewrite Python into Larky.

Pass order matters. Desugaring passes run first, the class rewriter runs
last because it restructures the module, and the import passes run on a
fresh metadata wrapper afterwards.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

import libcst
from libcst.codemod import CodemodContext, ContextAwareTransformer
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor

from py2star.asteez import (
    desugar,
    functionz,
    remove_exceptions,
    remove_types,
    rewrite_class,
    rewrite_comparisons,
    rewrite_imports,
    rewrite_loopz,
    rewrite_tests,
)

logger = logging.getLogger(__name__)


@dataclass
class Options:
    # rewrite unittest classes/asserts instead of plain classes
    for_tests: bool = False
    # use larky.mutablestruct instead of types.new_class for classes
    use_mutablestruct: bool = False
    # rewrite exceptions to use the Error module instead of fail
    use_error_not_fail: bool = False


def transform_passes(
    context: CodemodContext, options: Options
) -> List[ContextAwareTransformer]:
    passes = [
        rewrite_comparisons.RemoveIfNameEqualsMain(context),
        desugar.RewriteImplicitStringConcat(context),
        desugar.SwapByteStringPrefixes(context),
        desugar.SubMethodsWithLibraryCallsInstead(context),
        desugar.UnpackTargetAssignments(context),
        desugar.DesugarDecorators(
            context,
            exclude_decorators=(
                "staticmethod",
                "classmethod",
            )
            if options.use_mutablestruct
            else None,
        ),
        desugar.DesugarBuiltinOperators(context),
        desugar.DesugarSetSyntax(context),
        remove_exceptions.CommentTopLevelTryBlocks(context),
        desugar.RemoveDelKeyword(context),
        rewrite_loopz.WhileToForLoop(context),
        functionz.RewriteTypeChecks(context),
        functionz.GeneratorToFunction(context),
        rewrite_comparisons.UnchainComparison(context),
        rewrite_comparisons.IsComparisonTransformer(context),
        remove_types.RemoveTypesTransformer(context),
        remove_exceptions.RemoveExceptions(context),
    ]

    # must run last otherwise messes up all the other transformers above
    if options.for_tests:
        passes += [
            rewrite_tests.UnittestAssertMethodsRewriter(context),
            rewrite_tests.Unittest2Functions(context),
        ]
    else:
        # we don't want class to function rewriter for tests since
        # there's a special class rewriter for tests
        passes += [
            # only rewrite asserts in non-test contexts?
            remove_exceptions.AssertStatementRewriter(context),
            rewrite_class.ClassToFunctionRewriter(
                context,
                remove_decorators=False,
                use_mutablestruct=options.use_mutablestruct,
            ),
        ]
    return passes


def import_passes(context: CodemodContext) -> List[ContextAwareTransformer]:
    return [
        # apply imports queued by earlier passes
        AddImportsVisitor(context),
        RemoveImportsVisitor(context),
        rewrite_imports.RewriteImports(context),
        rewrite_imports.LarkyImportSorter(context),
    ]


def larkify(
    source: str,
    filename: Optional[str] = None,
    full_module_name: Optional[str] = None,
    options: Optional[Options] = None,
) -> libcst.Module:
    options = options or Options()
    program = libcst.parse_module(source)
    wrapper = libcst.MetadataWrapper(program)
    context = CodemodContext(
        wrapper=wrapper,
        filename=filename,
        full_module_name=full_module_name,
        scratch={"config": {"use_error_not_fail": options.use_error_not_fail}},
    )
    for t in transform_passes(context, options):
        logger.debug("running transformer: %s", t)
        with t.resolve(wrapper):
            program = t.transform_module(program)

    wrapper = libcst.MetadataWrapper(program)
    for t in import_passes(context):
        wrapper.resolve_many(t.get_inherited_dependencies())
        logger.debug("running transformer: %s", t)
        with t.resolve(wrapper):
            program = t.transform_module(program)
    return program
