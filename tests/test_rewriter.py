import logging
from lib2to3 import refactor
from textwrap import dedent

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.skip("unused")
def test_rewrite(simple_class, lib2to3_xfrms):
    _fixers = refactor.get_fixers_from_package("py2star.fixes")
    assert isinstance(_fixers, list) and len(_fixers) != 0

    def rt(fixers, options=None, explicit=None):
        return refactor.RefactoringTool(fixers, options, explicit)

    out = simple_class
    # out = open("sample_test2.py").read()
    for f in _fixers:
        # if not f.endswith("fix_exceptions"):
        #     continue
        tool = rt([f])
        out = str(tool.refactor_string(dedent(out), "simple_class.py"))
    print(out)
    assert out.strip().splitlines() == lib2to3_xfrms.strip().splitlines()
