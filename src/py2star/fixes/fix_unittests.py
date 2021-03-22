from .fix_declass import FixDeclass


class FixUnittests(FixDeclass):
    order = "pre"
    run_order = 7  # Fixers will be sorted by run order before execution
    # Lower numbers will be run first.

    PATTERN = """
      classdef< 'class' name=any ['(' 
           (power< 'unittest' trailer< '.' 'TestCase' > > | 'TestCase')
      ')'] ':'
         suite=suite
      >
    """
