import logging
import os
from argparse import Namespace
from typing import TextIO

import pytest

from py2star import cli

logger = logging.getLogger(__name__)

import ast

from py2star import rewriter
from py2star import starify


def test_rewrite():
    m = ast.parse(open("simple_class.py").read())
    starify.starify(m)
