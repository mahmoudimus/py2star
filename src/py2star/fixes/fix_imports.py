# -*- coding: utf-8 -*-
# Local imports
from lib2to3 import fixer_base
from lib2to3.fixer_base import BaseFix
from lib2to3.fixer_util import BlankLine, Name, attr_chain, syms, token

from birdseye import eye
from py2star import utils

MAPPING = {
    "json": ("stdlib", "json"),
    "builtins": ("stdlib", "json"),
    "unittest": ("stdlib", "unittest"),
    "escapes": ("vendor", "escapes"),
    "assertpy": ("vendor", "asserts"),
}


def alternates(members):
    return "(" + "|".join(map(repr, members)) + ")"


def build_pattern(mapping=None):
    if mapping is None:
        mapping = MAPPING
    mod_list = " | ".join(["module_name='%s'" % key for key in mapping])
    bare_names = alternates(mapping.keys())

    yield """name_import=import_name< 'import' ((%s) |
               multiple_imports=dotted_as_names< any* (%s) any* >) >
          """ % (
        mod_list,
        mod_list,
    )
    yield """import_from< 'from' (%s) 'import' ['(']
              ( any | import_as_name< any 'as' any > |
                import_as_names< any* >)  [')'] >
          """ % mod_list
    yield """import_name< 'import' (dotted_as_name< (%s) 'as' any > |
               multiple_imports=dotted_as_names<
                 any* dotted_as_name< (%s) 'as' any > any* >) >
          """ % (
        mod_list,
        mod_list,
    )

    # Find usages of module members in code e.g. thread.foo(bar)
    yield "power< bare_with_attr=(%s) trailer<'.' any > any* >" % bare_names


class FixImports(fixer_base.BaseFix):
    BM_compatible = True
    keep_line_order = True

    order = "post"

    # We want to run this fixer real late,so fix_import can just clean
    # everything up
    run_order = 9

    def __init__(self, options, log):
        super().__init__(options, log)
        self.replace = {}

    @staticmethod
    def build_pattern():
        return "|".join(build_pattern(MAPPING))

    def compile_pattern(self):
        # We override this, so MAPPING can be pragmatically altered and the
        # changes will be reflected in PATTERN.
        self.PATTERN = self.build_pattern()
        super(FixImports, self).compile_pattern()

    # Don't match the node if it's within another match.
    def match(self, node):
        match = super(FixImports, self).match
        results = match(node)
        if not results:
            return False
        # Module usage could be in the trailer of an attribute lookup, so we
        # might have nested matches when "bare_with_attr" is present.
        if "bare_with_attr" not in results and any(
            match(obj) for obj in attr_chain(node, "parent")
        ):
            return False
        return results

    def start_tree(self, tree, filename):
        super(FixImports, self).start_tree(tree, filename)

    @eye
    def transform(self, node, results):
        import_mod = results.get("module_name")
        if not import_mod:
            # Replace usage of the module.
            bare_name = results["bare_with_attr"][0]
            new_name = self.replace.get(bare_name.value)
            if new_name:
                bare_name.replace(Name(new_name, prefix=bare_name.prefix))
            return

        mod_name = import_mod.value
        try:
            package, new_name = MAPPING[mod_name]
        except KeyError:
            self.warning(node, f"Cannot find mapping for {mod_name}. skipping")
            return

        # add new Larky import to the file
        utils.add_larky_import(package, new_name, node)

        import_mod = self._import_replace(import_mod)
        # import_mod = self._import_rename(new_name, import_mod)
        if "name_import" in results:
            # If it's not a "from x import x, y" or "import x as y" import,
            # marked its usage to be replaced.
            self.replace[mod_name] = new_name

        if "multiple_imports" in results:
            # This is a nasty hack to fix multiple imports on a line (e.g.,
            # "import StringIO, urlparse"). The problem is that I can't
            # figure out an easy way to make a pattern recognize the keys of
            # MAPPING randomly sprinkled in an import statement.
            results = self.match(node)
            if bool(results):
                self.transform(node, results)

        return import_mod

    @staticmethod
    def _import_replace(import_mod):
        """
        replace the current import with a blank line instead of rewriting
        :param import_mod:
        :return: a blank line representing a replaced import
        """
        n = BlankLine()
        n.prefix = import_mod.prefix
        return n

    @staticmethod
    def _import_rename(new_name, import_mod):
        """
        Just rename the import module to the new name
        :param new_name:
        :param import_mod:
        :return: renames import_mod to new_name
        """
        import_mod.replace(Name(new_name, prefix=import_mod.prefix))
        return import_mod
