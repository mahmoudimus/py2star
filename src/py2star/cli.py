import argparse
import ast
import inspect
import logging
import string
import sys
import textwrap

from py2star.asteez import functionz
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


def execute(args: argparse.Namespace) -> None:
    if args.command == "defs":
        gen = find_definitions(args.filename)
        for definition in gen:
            print(definition.rstrip())
    elif args.command == "tests":
        tree = ast.parse(open(args.filename).read())
        s = functionz.testsuite_generator(tree)
        print(s)
    elif args.command == "xxx":
        pass


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

    args = parser.parse_args()
    set_log_lvl(args)
    logger.debug(args)
    execute(args)


if __name__ == "__main__":
    main()
