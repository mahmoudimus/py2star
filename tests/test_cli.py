import logging
import os
from argparse import Namespace

import pytest

from py2star import cli

logger = logging.getLogger(__name__)


@pytest.fixture()
def fixture_data():
    return open("fixture_data.py").read()


def test_execute(fixture_data):
    namespace = Namespace(

    )
    assert namespace
    print(namespace)
    cli.execute(namespace)
