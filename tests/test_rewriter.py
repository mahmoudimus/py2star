import ast
import logging
from lib2to3 import refactor

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture()
def program() -> ast.Module:
    m = ast.parse(open("simple_class.py").read())
    return m


def test_rewrite():
    _fixers = refactor.get_fixers_from_package("py2star.fixes")
    assert isinstance(_fixers, list) and len(_fixers) != 0

    def rt(fixers, options=None, explicit=None):
        return refactor.RefactoringTool(fixers, options, explicit)

    out = open("simple_class.py").read()
    # out = open("sample_test.py").read()
    for f in _fixers:
        if not f.endswith("fix_asserts"):
            continue
        tool = rt([f])
        out = str(tool.refactor_string(out, "simple_class.py"))
    print(out)
    return out
