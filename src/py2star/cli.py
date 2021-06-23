import argparse
import ast
import io
import logging
import re
import sys
import tokenize
from lib2to3 import refactor
from typing import Optional, Pattern

import lib3to6 as three2six
import libcst
from lib3to6 import common as three2six_common
from libcst.codemod import CodemodContext
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor
from py2star.asteez import (
    functionz,
    remove_exceptions,
    remove_types,
    rewrite_class,
    rewrite_comparisons,
    rewrite_imports,
    rewrite_loopz,
    rewrite_tests,
)
from py2star.tokenizers import find_definitions
from py2star.utils import ReIndenter

logger = logging.getLogger(__name__)


class ArgparseHelper(argparse._HelpAction):
    """
    Used to help print top level '--help' arguments from argparse
    when used with subparsers
    Usage:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-h', '--help', action=ArgparseHelper,
                        help='show this help message and exit')
    # add subparsers below these lines
    """

    def __call__(self, parser, namespace, values, option_string=None):
        parser.print_help()
        print()

        subparsers_actions = [
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        for subparsers_action in subparsers_actions:
            for choice, subparser in list(subparsers_action.choices.items()):
                print("Command '{}'".format(choice))
                print(subparser.format_usage())

        parser.exit()


def conf_logging():
    _log = logging.getLogger()

    _msg_template = "%(asctime)s : %(levelname)s : %(name)s : %(message)s"
    formatter = logging.Formatter(_msg_template)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    _log.addHandler(handler)


def set_log_lvl(args, log_level=None):
    conf_logging()
    _log = logging.getLogger()

    if log_level is None:  # Not sure if log_level can be the number 0
        log_level = args.log_level.upper()
        # make logging less verbose
        logging.getLogger("lib2to3.main").setLevel(logging.WARN)
        logging.getLogger("RefactoringTool").setLevel(logging.WARN)
    if isinstance(log_level, str):
        log_level = log_level.upper()  # check to make sure it is upper
        log_level = getattr(logging, log_level)
    _log.setLevel(log_level)


def _add_common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument(
        "-l",
        "--log-level",
        default="info",
        help="Set the logging level",
        choices=["debug", "info", "warn", "warning", "error", "critical"],
    )
    p.add_argument(
        "-p",
        "--pkg-path",
        default=None,
        help="Override the default pkg path for resolving local imports",
    )
    return p


def detect_encoding(filename):
    with open(filename, "rb") as f:
        try:
            encoding, _ = tokenize.detect_encoding(f.readline)
        except SyntaxError as se:
            logger.exception("%s: SyntaxError: %s", filename, se)
            return
    return encoding


def fixup_indentation(fileobj):
    # return f.read()
    r = ReIndenter(fileobj)
    r.run()  # ensure spaces vs tabs

    with io.StringIO() as o:
        o.writelines(r.after)
        o.flush()
        return o.getvalue()


def safe_read(filename):
    encoding = detect_encoding(filename)
    try:
        with open(filename, encoding=encoding) as f:
            out = fixup_indentation(f)
    except IOError as msg:
        logger.exception("%s: I/O Error: %s", filename, msg)
        raise msg
    return out


def onfixes(out, fixers, doprint=True):
    if not fixers:
        _fixers = refactor.get_fixers_from_package("py2star.fixes")
    else:
        _fixers = [
            i
            for i in refactor.get_fixers_from_package("py2star.fixes")
            for x in fixers
            if i.endswith(x)
        ]

    # out = _lib3to6(filename, out)

    for f in _fixers:
        logger.debug("running fixer: %s", f)
        # if not f.endswith("fix_asserts"):
        #     continue
        tool = refactor.RefactoringTool([f])
        out = tool.refactor_string(out, "simple_class.py")
        out = str(out)
    if doprint:
        print(out)
    return out


def _lib3to6(filename, source_text, install_requires=None, mode="enabled"):
    cfg = three2six.packaging.eval_build_config(
        target_version="3.5",
        install_requires=install_requires,
        default_mode=mode,
    )

    ctx = three2six_common.BuildContext(cfg, filename)
    try:
        fixed_source_text = three2six.transpile.transpile_module(
            ctx, source_text
        )
    except three2six_common.CheckError as err:
        loc = filename
        if err.lineno >= 0:
            loc += "@" + str(err.lineno)

        err.args = (loc + " - " + err.args[0],) + err.args[1:]
        raise

    return fixed_source_text


def larkify(filename, args):
    # TODO: select larkifiers dynamically? maybe look into instagram/fixers?
    fixers = args.fixers
    out = safe_read(filename)
    if fixers:
        doprint = args.log_level.lower() == "debug"
        out = onfixes(out, fixers, doprint=doprint)

    program = libcst.parse_module(out)
    wrapper = libcst.MetadataWrapper(program)
    context = CodemodContext(
        wrapper=wrapper,
        filename=filename,
        full_module_name=_full_module_name(args.pkg_path, filename),
    )
    transformers = [
        remove_exceptions.RewriteImplicitStringConcat(context),
        remove_exceptions.SubMethodsWithLibraryCallsInstead(context),
        remove_exceptions.UnpackTargetAssignments(context),
        remove_exceptions.DesugarDecorators(context),
        remove_exceptions.DesugarBuiltinOperators(context),
        remove_exceptions.DesugarSetSyntax(context),
        remove_exceptions.CommentTopLevelTryBlocks(context),
        rewrite_imports.RemoveDelKeyword(context),
        rewrite_loopz.WhileToForLoop(context),
        functionz.RewriteTypeChecks(context),
        functionz.GeneratorToFunction(context),
        rewrite_comparisons.UnchainComparison(context),
        rewrite_comparisons.RemoveIfNameEqualsMain(context),
        rewrite_comparisons.IsComparisonTransformer(context),
        remove_types.RemoveTypesTransformer(context),
        remove_exceptions.RemoveExceptions(context),
    ]

    # must run last otherwise messes up all the other transformers above
    if args.for_tests:
        # TODO: can this by dynamic so we don't pass this in?
        transformers += [
            rewrite_tests.AssertStatementRewriter(context),
            rewrite_tests.Unittest2Functions(context),
        ]
    else:
        # we don't want class to function rewriter for tests since
        # there's a special class rewriter for tests
        transformers += [
            rewrite_class.ClassToFunctionRewriter(
                context, remove_decorators=False
            )
        ]
    for t in transformers:
        logger.debug("running transformer: %s", t)
        with t.resolve(wrapper):
            program = t.transform_module(program)

    transformers = [
        AddImportsVisitor(context),
        RemoveImportsVisitor(context),
        rewrite_imports.RewriteImports(context),
        rewrite_imports.LarkyImportSorter(context),
    ]

    wrapper = libcst.MetadataWrapper(program)
    for t in transformers:
        wrapper.resolve_many(t.get_inherited_dependencies())
        logger.debug("running transformer: %s", t)
        with t.resolve(wrapper):
            program = t.transform_module(program)

    print(program.code)
    if args.for_tests:
        tree = ast.parse(program.code)
        s = functionz.testsuite_generator(tree)
        print(s)


DOT_PY: Pattern[str] = re.compile(r"(__init__)?\.py$")


def _module_name(path: str) -> Optional[str]:
    return DOT_PY.sub("", path).replace("/", ".").rstrip(".")


def _full_module_name(pkg_path, filename):
    # use file_path to compute relative path?
    # >>> os.path.relpath("/src/python-jose/jose/jwt.py", "/src/python-jose")
    # 'jose/jwt.py'
    if not pkg_path:
        return None
    mname = _module_name(filename)
    if not mname.startswith(pkg_path + "."):
        return f"{pkg_path}.{mname}"
    return mname


def execute(args: argparse.Namespace) -> None:
    if args.command == "defs":
        gen = find_definitions(args.filename)
        for definition in gen:
            print(definition.rstrip())
    elif args.command == "tests":
        tree = ast.parse(open(args.filename).read())
        s = functionz.testsuite_generator(tree)
        print(s)
    elif args.command == "fixers":
        onfixes(args.filename, fixers=args.fixers)
    elif args.command == "larkify":
        larkify(args.filename, args)


def main():
    parser = argparse.ArgumentParser(description="", add_help=False)
    parser.add_argument(
        "-h",
        "--help",
        action=ArgparseHelper,
        help="show this help message and exit",
    )
    subparsers = parser.add_subparsers(help="commands", dest="command")
    parser = _add_common(parser)

    # args here are applied to all sub commands using the `parents` parameter
    base = argparse.ArgumentParser(add_help=False)

    # subcommand 1 -- function commands
    defs = subparsers.add_parser(
        "defs", help="function definitions", parents=[base]
    )
    defs.add_argument("filename")

    # subcommand 2 -- tests command
    tests = subparsers.add_parser(
        "tests",
        help="Enumerate functions and dump to test suite",
        parents=[base],
    )
    tests.add_argument("filename")

    # subcommand 3 -- pattern finders
    fixpattern = subparsers.add_parser(
        "fixpattern",
        help="Easily determine PATTERN for a new fix",
        parents=[base],
    )
    fixpattern.add_argument("statement")

    # subcommand 3 -- pattern finders
    fixers = subparsers.add_parser(
        "fixers",
        help="fixer",
        parents=[base],
    )
    fixers.add_argument("filename")
    fixers.add_argument("--fixers", default=[], required=False, action="append")

    larkify = subparsers.add_parser(
        "larkify",
        help="larkify",
        parents=[base],
    )
    larkify.add_argument("filename")
    larkify.add_argument(
        "--fixers", default=[], required=False, action="append"
    )
    larkify.add_argument(
        "--asteez", default=[], required=False, action="append"
    )
    larkify.add_argument(
        "-for-tests", "-t", default=False, action="store_true", help="for tests"
    )

    args = parser.parse_args()
    set_log_lvl(args)
    logger.debug(args)
    execute(args)


if __name__ == "__main__":
    main()
