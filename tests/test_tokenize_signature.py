import logging
import os
from argparse import Namespace
from typing import TextIO

import pytest

from py2star import cli

logger = logging.getLogger(__name__)


from py2star.tokenize_signature import find_definitions


def test_find_definitions():
    defs = list(find_definitions("fixture_data.py"))
    assert len(defs) != 0
    assert len(defs) == 3
    print(defs)