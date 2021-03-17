# def list_test_cases(class_):
#     """Return a list of TestCase instances given a TestCase class
#
#     This is useful when you have defined test* methods on your TestCase class.
#     """
#     return unittest.TestLoader().loadTestsFromTestCase(class_)

import sys
import ast
import astunparse


def starify(module: ast.Module):
    # Collect all the classes which inherit from ComponentBase
    clses = []
    for block in module.body:
        if isinstance(block, ast.ClassDef):
            clses.append(block)
            # if "ComponentBase" in [b.id for b in block.bases]:
            #     clses.append(block)


    # Inspect each class's __init__ method for an argument called "id" which we'll assume
    # means that the class should map to an XML element that has an id attribute
    for cls in clses:
        print(cls.name)
        for block in cls.body:
            if isinstance(block, ast.FunctionDef):
                if block.name == "__init__":
                    args = block.args
                    print('\t', len(args.args), "argument __init__")
                    if "id" in [a for a in args.args]:
                        print("Has ID")
                        cls.body.insert(0, ast.Assign(targets=[ast.Name(id="requires_id")], value=ast.Name(id="True")))
                        break
        else:
            cls.body.insert(0, ast.Assign(targets=[ast.Name(id="requires_id")], value=ast.Name(id="False")))


    # Rewrite the write method as "write_content", removing the top-most with expression
    for cls in clses:
        print(cls.name)
        for block in cls.body:
            if isinstance(block, ast.FunctionDef):
                if block.name == "write":
                    assert len(block.body) == 1
                    block.name = "write_content"
                    if isinstance(block.body[0], ast.With):
                        block.body = block.body[0].body

    # Render the AST back into text
    astunparse.Unparser(module)
