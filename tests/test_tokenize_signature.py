import logging

logger = logging.getLogger(__name__)


from py2star.tokenizers import find_definitions


def test_find_definitions(fixture_file):
    defs = list(find_definitions(fixture_file))
    assert len(defs) != 0
    assert len(defs) == 3
    print(defs)
