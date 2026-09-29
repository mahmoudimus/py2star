import argparse
import io
import logging
import re
import sys
import tokenize
from typing import Optional, Pattern

import libcst
from py2star import pipeline
from py2star.asteez import functionz
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


def larkify(filename, args):
    options = pipeline.Options(
        for_tests=args.for_tests,
        use_mutablestruct=args.use_mutablestruct,
        use_error_not_fail=args.use_error_not_fail,
    )
    program = pipeline.larkify(
        safe_read(filename),
        filename=filename,
        full_module_name=_full_module_name(args.pkg_path, filename),
        options=options,
    )
    print(program.code)
    if args.for_tests:
        print(functionz.testsuite_generator(program))


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
        with open(args.filename) as f:
            tree = libcst.parse_module(f.read())
        print(functionz.testsuite_generator(tree))
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

    larkify = subparsers.add_parser(
        "larkify",
        help="larkify",
        parents=[base],
    )
    # larkify.add_argument("filename", type=argparse.FileType("r"), default="-")
    larkify.add_argument("filename")
    larkify.add_argument(
        "--use-error-not-fail",
        action="store_true",
        default=False,
        help="Rewrites exceptions to use the Error module instead of fail",
    )
    larkify.add_argument(
        "--use-mutablestruct",
        action="store_true",
        default=False,
        help="Uses mutablestruct instead of types.new_class for class translation",
    )
    larkify.add_argument(
        "-for-tests", "-t", default=False, action="store_true", help="for tests"
    )

    args = parser.parse_args()
    set_log_lvl(args)
    logger.debug(args)
    execute(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            import ipdb as debugger
        except ImportError:
            import pdb as debugger
        debugger.post_mortem(exc.__traceback__)
