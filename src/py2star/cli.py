import argparse
import ast
import inspect
import logging
import string
import sys
import textwrap
from lib2to3 import refactor

import astunparse
from py2star import asteez
from py2star.asteez import (
    functionz,
    remove_self,
    rewrite_chained_comparisons,
    rewrite_fstring,
    rewrite_loopz,
)
from py2star.tokenizers import find_definitions

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
    return p


def onfixes(filename, fixers, doprint=True):
    if not fixers:
        _fixers = refactor.get_fixers_from_package("py2star.fixes")
    else:
        _fixers = [
            i
            for i in refactor.get_fixers_from_package("py2star.fixes")
            for x in fixers
            if i.endswith(x)
        ]

    with open(filename, "r") as f:
        out = f.read()

    for f in _fixers:
        logger.debug("running fixer: %s", f)
        # if not f.endswith("fix_asserts"):
        #     continue
        tool = refactor.RefactoringTool([f])
        out = str(tool.refactor_string(out, "simple_class.py"))
    if doprint:
        print(out)
    return out


def larkify(filename, fixers, astrw):
    out = onfixes(filename, fixers, doprint=False)
    # TODO: dynamic
    #  asteez.get_ast_rewriters_from_package("py2star.asteez")

    program = ast.parse(out)
    rewritten = program

    for l in [
        remove_self.FunctionParameterStripper(["self"]),
        remove_self.AttributeGetter(["self"]),
        rewrite_loopz.WhileToForLoop(),
        functionz.GeneratorToFunction(),
        rewrite_chained_comparisons.UnchainComparison(),
    ]:
        rewritten = l.visit(rewritten)
    print(astunparse.unparse(rewritten))


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
        larkify(args.filename, fixers=args.fixers, astrw=args.asteez)


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

    args = parser.parse_args()
    set_log_lvl(args)
    logger.debug(args)
    execute(args)


if __name__ == "__main__":
    main()
