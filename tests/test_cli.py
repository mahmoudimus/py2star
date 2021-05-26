import logging
from argparse import Namespace

from py2star import cli

logger = logging.getLogger(__name__)


def test_execute(fixture_file):
    namespace = Namespace(command="defs", filename=fixture_file)
    assert namespace
    print(namespace)
    cli.execute(namespace)
