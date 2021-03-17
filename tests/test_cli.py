import logging
import os
from argparse import Namespace
from typing import TextIO

import pytest

from py2star import cli

logger = logging.getLogger(__name__)


@pytest.fixture()
def fixture_file() -> TextIO:
    return open("fixture_data.py")


@pytest.fixture()
def fixture(fixture_file):
    return fixture_file.read()


def test_execute():
    namespace = Namespace(
        filename="fixture_data.py"
    )
    assert namespace
    print(namespace)
    cli.execute(namespace)
