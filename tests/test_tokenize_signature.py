import logging

logger = logging.getLogger(__name__)


from py2star.tokenizers import find_definitions


def test_find_definitions():
    defs = list(find_definitions("fixture_data.py"))
    assert len(defs) != 0
    assert len(defs) == 3
    print(defs)
