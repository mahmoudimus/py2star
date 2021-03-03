import logging
import argparse
import os
import pathlib
import pprint
import sys
import time
from datetime import datetime, timedelta


from tokenize_signature import find_definitions


logger = logging.getLogger(__name__)


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


def _add_options(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument(
        "-l",
        "--log-level",
        default="info",
        help="Set the logging level",
        choices=["debug", "info", "warn", "warning", "error", "critical"]
    )
    p.add_argument("filename")
    return p


def execute(args: argparse.Namespace) -> None:
    gen = find_definitions(args.filename)
    for definition in gen:
        print(definition.rstrip())


def main():
    parser = argparse.ArgumentParser(description="")
    parser = _add_options(parser)
    args = parser.parse_args()
    set_log_lvl(args)
    logger.debug(args)
    execute(args)


if __name__ == "__main__":
    main()
