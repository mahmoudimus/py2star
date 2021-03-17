import ast
import _ast
from _ast import AST
from collections import OrderedDict
from typing import (
    Set,
)

class Rewrite(ast.NodeVisitor):
    def __init__(self):
        self.indentation = 0
        self.in_new_line = True
        self.nested_scope = [False]
        self.latest_class = False
        self.ar_ops = {
            _ast.Add: "+",
            _ast.Sub: "-",
            _ast.Mult: "*",
            _ast.MatMult: "@",
            _ast.Div: "/",
            _ast.Mod: "%",
            _ast.Pow: "**",
            _ast.LShift: "<<",
            _ast.RShift: ">>",
            _ast.BitOr: "|",
            _ast.BitXor: "^",
            _ast.BitAnd: "&",
            _ast.FloorDiv: "//",
        }

    def __enter__(self):
        self.indentation += 4
        self.nested_scope.append(True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.indentation -= 4
        self.nested_scope.pop()

    def visit(self, node, new_line=True):
        """
        Visit a node, this overrides NodeVisitor visit method as we need to
        start a new line between each body element.
        """
        method = "visit_" + node.__class__.__name__
        visitor = getattr(self, method, self.generic_visit)
        visitor_ = visitor(node)
        if new_line and not isinstance(node, ast.Module):
            self.new_line()
        return visitor_

    def generic_visit(self, node):
        """Called if no explicit visitor function exists for a node."""
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, AST):
                        if isinstance(node, _ast.Module):
                            self.visit(item)
                        else:
                            self.visit(item, False)
            elif isinstance(value, AST):
                self.visit(value, False)

    def _prepare_line(self, value, _new_line, _is_iterable, _special_attribute):
        """
        Prepares a line to be printed.
        :param value: Value required to print.
        :param _new_line: End line with a \n.
        :param _is_iterable: Is the value iterable (list, tuple, etc...).
        :param _special_attribute: Special attribute that we need to print instead of value.
        :return: None.
        """
        to_print = ""
        if _new_line and not value:
            to_print = "\n"
            self.in_new_line = True
            return to_print
        if self.in_new_line:
            to_print = " " * self.indentation  # Prepare indentation first.
            self.in_new_line = False
        if _is_iterable:
            assert hasattr(value, "__iter__")  # Make sure the item is iterable.
            iterable_size = len(value)
            for i, item in enumerate(value):
                to_print += (
                    str(item)
                    if not _special_attribute
                    else f"{getattr(item, _special_attribute)}"
                )
                if i + 1 != iterable_size:
                    to_print += ", "
        else:
            to_print += (
                f"{value}"
                if not _special_attribute
                else f"{getattr(value, _special_attribute)}"
            )
        if _new_line:
            to_print += "\n"
            self.in_new_line = True
        return to_print

    def print(
        self,
        value,
        *,
        _new_line=False,
        _is_iterable=False,
        _special_attribute=None,
        _use_visit=False,
    ):
        """
        outputs required value to target file.
        :param value: Value required to print.
        :param _new_line: End line with a \n.
        :param _is_iterable: Is the value iterable (list, tuple, etc...).
        :param _special_attribute: Special attribute that we need to print instead of value.
        :param _use_visit: should item be printed directly or use visit_class() method.
        :return: None.
        """
        if not _use_visit:
            to_print = self._prepare_line(
                value, _new_line, _is_iterable, _special_attribute
            )
            file.write(to_print)
        elif _is_iterable and _use_visit:
            for i, item in enumerate(value):
                self.visit(item, new_line=False)
                if i + 1 != len(value):
                    self.print(", ")

    def new_line(self, num=1):
        [self.print("", _new_line=True) for _ in range(num)]

    def visit_Module(self, node):
        for i, body_node in enumerate(node.body):
            if i == 0 and ast.get_docstring(node):
                self.visit_Constant(body_node.value, is_docstring=True)
            else:
                self.visit(body_node)
            if (
                i + 1 != len(node.body)
                and isinstance(node.body[i + 1], (_ast.FunctionDef, _ast.ClassDef))
                and not isinstance(node.body[i], (_ast.FunctionDef, _ast.ClassDef))
            ):
                self.new_line(2)

    def visit_Import(self, node):
        imports_list = node.names
        for i, name in enumerate(imports_list):
            self.print(
                f"import {name.name}",
                _new_line=True if i + 1 != len(imports_list) else False,
            )

    def visit_ImportFrom(self, node):
        import_list = node.names
        self.print(f"from {node.module} import ")
        self.print(import_list, _is_iterable=True, _special_attribute="name")

    def visit_UnaryOp(self, node):
        ops = {_ast.Not: "not", ast.Invert: "~", ast.UAdd: "+", ast.USub: "-"}
        self.print(f"{ops[type(node.op)]}")
        if isinstance(node.op, _ast.Not):
            self.print(" ")
        self.visit(node.operand, False)

    def visit_BinOp(self, node):
        self.visit(node.left, False)
        self.print(f" {self.ar_ops[type(node.op)]} ")
        self.visit(node.right, False)

    def visit_AugAssign(self, node):
        self.visit(node.target, new_line=False)
        self.print(f" {self.ar_ops[type(node.op)]}= ")
        self.visit(node.value, new_line=False)

    def visit_Constant(self, node, is_docstring=False):
        if isinstance(node.value, str):
            self.print('"')
            if is_docstring:
                self.print('""')
        self.print(node.value)
        if isinstance(node.value, str):
            self.print('"')
            if is_docstring:
                self.print('""')
                self.new_line()

    def visit_Name(self, node):
        self.print(node.id)

    def visit_Continue(self, node):
        self.print("continue")

    def visit_Break(self, node):
        self.print("break")

    def visit_Delete(self, node):
        self.print("del ")
        for i, target in enumerate(node.targets):
            self.visit(target, new_line=False)
            if i + 1 != len(node.targets):
                self.print(", ")

    def visit_BoolOp(self, node):
        op = "and" if isinstance(node.op, _ast.And) else "or"
        for i, value in enumerate(node.values):
            self.visit(value, new_line=False)
            if i + 1 != len(node.values):
                self.print(f" {op} ")

    def visit_List(self, node):
        self.print("[")
        self.print(node.elts, _is_iterable=True, _use_visit=True)
        self.print("]")

    def visit_Dict(self, node):
        self.print("{")
        self.new_line()
        with self:
            for key, value in zip(node.keys, node.values):
                self.visit(key, new_line=False)
                self.print(": ")
                self.visit(value, new_line=False)
                self.print(",")
                self.new_line()
        self.print("}")

    def visit_Tuple(self, node):
        self.print("(")
        self.print(node.elts, _is_iterable=True, _use_visit=True)
        self.print(")")

    def visit_Pass(self, node):
        self.print("pass")

    def visit_Return(self, node):
        self.print("return")
        if node.value:
            self.print(" ")
            self.visit(node.value, new_line=False)

    def visit_Global(self, node):
        self.print("global ")
        self.print(node.names, _is_iterable=True)

    def visit_Nonlocal(self, node):
        self.print("nonlocal ")
        self.print(node.names, _is_iterable=True)

    def visit_NamedExpr(self, node):
        self.print("(")
        self.visit(node.target, new_line=False)
        self.print(f" := ")
        self.visit(node.value, new_line=False)
        self.print(")")

    def visit_Assign(self, node):
        for target in node.targets:
            self.visit(target, False)
            self.print(" = ")
        self.visit(node.value, False)

    def visit_Compare(self, node):
        ops = {
            _ast.Eq: "==",
            _ast.NotEq: "!=",
            _ast.Lt: "<",
            _ast.LtE: "<=",
            _ast.Gt: ">",
            _ast.GtE: ">=",
            _ast.Is: "is",
            _ast.IsNot: "is not",
            _ast.In: "in",
            _ast.NotIn: "not in",
        }
        self.visit(node.left, new_line=False)
        self.print(" ")
        for i, (op, comp) in enumerate(zip(node.ops, node.comparators)):
            self.print(f"{ops[type(op)]} ")
            self.visit(comp, new_line=False)
            if i + 1 != len(node.ops):
                self.print(" ")

    def visit_Subscript(self, node):
        self.visit(node.value, new_line=False)
        self.visit(node.slice, new_line=False)

    def visit_Index(self, node):
        self.print("[")
        self.visit(node.value, new_line=False)
        self.print("]")

    def visit_Slice(self, node):
        self.print("[")
        if node.lower:
            self.visit(node.lower, new_line=False)
        self.print(":")
        if node.upper:
            self.visit(node.upper, new_line=False)
        if node.step:
            self.print(":")
            self.visit(node.step, new_line=False)
        self.print("]")

    def visit_Assert(self, node):
        self.print("assert ")
        self.visit(node.test, new_line=False)
        if node.msg:
            self.print(", ")
            self.visit(node.msg, new_line=False)

    def visit_keyword(self, node):
        if node.arg:
            self.print(f"{node.arg}=")
        else:
            self.print(f"**")
        self.visit(node.value, new_line=False)

    def visit_Attribute(self, node):
        self.visit(node.value, new_line=False)
        self.print(".")
        self.print(node.attr)

    def visit_Raise(self, node):
        self.print("raise")
        if node.exc:
            self.print(" ")
            self.visit(node.exc, new_line=False)
        if node.cause:
            self.print(" from ")
            self.visit(node.cause, new_line=False)

    def visit_Try(self, node):
        self.print("try:", _new_line=True)
        with self:
            self._visit_list(node.body)
        for handle in node.handlers:
            self.visit(handle, new_line=False)
        if node.orelse:
            self.new_line()
            self.print("else:", _new_line=True)
            with self:
                self._visit_list(node.orelse)
        if node.finalbody:
            self.print("finally:", _new_line=True)
            with self:
                self._visit_list(node.finalbody, _new_line_at_finish=False)

    def visit_ExceptHandler(self, node):
        self.print("except")
        if node.type:
            self.print(" ")
            self.visit(node.type, new_line=False)
        if node.name:
            self.print(f" as {node.name}")
        self.print(":", _new_line=True)
        with self:
            self._visit_list(node.body, _new_line_at_finish=False)

    def visit_Starred(self, node):
        self.print("*")
        self.visit(node.value, new_line=False)

    def visit_arguments(self, node):
        ordered_only_pos, ordered_args = Rewrite._ordered_pos_arg_default(
            node.posonlyargs, node.args, node.defaults
        )
        for i, (key, value) in enumerate(ordered_only_pos.items()):
            self.print(key)
            if value:
                self.print(f"=")
                self.visit(value[0], new_line=False)
            if i + 1 != len(ordered_only_pos):
                self.print(", ")
            else:
                self.print(", /")
        if ordered_only_pos and (
            ordered_args or node.vararg or node.kwonlyargs or node.kwarg
        ):
            self.print(", ")
        for i, (key, value) in enumerate(ordered_args.items()):
            self.print(key)
            if value:
                self.print(f"=")
                self.visit(value[0], new_line=False)
            if (
                i + 1 != len(ordered_args)
                or node.vararg
                or node.kwonlyargs
                or node.kwarg
            ):
                self.print(", ")
        if (ordered_args or ordered_only_pos) and (
            node.vararg or node.kwonlyargs or node.kwarg
        ):
            self.print("*")
        if node.vararg:
            if not (ordered_args or ordered_only_pos):
                self.print("*")
            self.print(f"{node.vararg.arg}")
        elif not (ordered_args or ordered_only_pos) and (node.kwonlyargs or node.kwarg):
            self.print("*, ")
        if (ordered_args or ordered_only_pos) and (node.kwonlyargs or node.kwarg):
            self.print(", ")
        for i, item in enumerate(node.kwonlyargs):
            self.print(item.arg)
            if node.kw_defaults:
                if node.kw_defaults[0] is not None:
                    self.print("=")
                    self.visit(node.kw_defaults[i], new_line=False)
            if i + 1 != len(node.kwonlyargs):
                self.print(", ")
        if (
            ordered_args or ordered_only_pos or node.vararg or node.kwonlyargs
        ) and node.kwarg:
            self.print(f", **{node.kwarg.arg}")

    def visit_withitem(self, node):
        self.visit(node.context_expr, new_line=False)
        if node.optional_vars:
            self.print(" as ")
            self.visit(node.optional_vars, new_line=False)

    def visit_With(self, node):
        self.print("with ")
        for i, element in enumerate(node.items):
            self.visit(element, new_line=False)
            if i + 1 != len(node.items):
                self.print(", ")
        self.print(":", _new_line=True)
        with self:
            for i, element in enumerate(node.body):
                if i + 1 != len(node.body):
                    self.visit(element)
                else:
                    self.visit(element, new_line=False)

    def visit_FunctionDef(self, node):
        for decorator in node.decorator_list:
            self.print("@")
            self.visit(decorator)
        self.print(f"def {node.name}(")
        if node.args:
            self.visit(node.args, new_line=False)
        self.print("):", _new_line=True)
        with self:
            if ast.get_docstring(node):
                self.visit_Constant(node.body[0].value, is_docstring=True)
            for i, element in enumerate(node.body):
                if ast.get_docstring(node) and i == 0:
                    continue
                self.visit(element, new_line=i + 1 != len(node.body))
        if self.latest_class:
            return
        self.new_line(1 if self.nested_scope[-1] else 2)

    def visit_ClassDef(self, node):
        for decorator in node.decorator_list:
            self.print("@")
            self.visit(decorator)
        self.print(f"class {node.name}")
        if node.bases:
            self.print("(")
            for i, base in enumerate(node.bases):
                self.visit(base, new_line=False)
                if i + 1 != len(node.bases):
                    self.print(", ")
        if node.keywords:
            self.print(", ")
            for i, keyword in enumerate(node.keywords):
                self.visit(keyword, new_line=False)
                if i + 1 != len(node.keywords):
                    self.print(", ")
        if node.bases or node.keywords:
            self.print(")")
        self.print(":", _new_line=True)
        with self:
            for i, element in enumerate(node.body):
                if ast.get_docstring(node) and i == 0:
                    self.visit_Constant(node.body[0].value, is_docstring=True)
                    continue
                if i + 1 == len(node.body):
                    self.latest_class = True
                self.visit(element, new_line=i + 1 != len(node.body))
                self.latest_class = False
        self.new_line(1 if self.nested_scope[-1] else 2)

    def visit_If(self, node):
        self.print("if ")
        self._block_flow(node=node, first_attr="test", is_if=True)

    def visit_While(self, node):
        self.print("while ")
        self._block_flow(node=node, first_attr="test")

    def visit_For(self, node):
        self.print("for ")
        self.visit(node.target, new_line=False)
        self.print(" in ")
        self._block_flow(node=node, first_attr="iter")

    def visit_Call(self, node):
        self.visit(node.func, new_line=False)
        self.print("(")
        for i, arg in enumerate(node.args):
            self.visit(arg, new_line=False)
            if i + 1 != len(node.args) or node.keywords:
                self.print(", ")
        for i, kwarg in enumerate(node.keywords):
            self.visit(kwarg, new_line=False)
            if i + 1 != len(node.keywords):
                self.print(", ")
        self.print(")")

    def visit_ListComp(self, node):
        self.print("[")
        self.visit(node.elt, new_line=False)
        for generator in node.generators:
            self.print(" for ")
            self.visit(generator, new_line=False)
        self.print("]")

    def visit_IfExp(self, node):
        self.visit(node.body, new_line=False)
        self.print(" if ")
        self.visit(node.test, new_line=False)
        self.print(" else ")
        self.visit(node.orelse, new_line=False)

    def visit_comprehension(self, node):
        self.visit(node.target, new_line=False)
        self.print(" in ")
        self.visit(node.iter, new_line=False)
        if node.ifs:
            for if_liner in node.ifs:
                self.print(" if ")
                self.visit(if_liner, new_line=False)

    def _block_flow(self, node, first_attr, is_if=False):
        node_attr = getattr(node, first_attr)
        self.visit(node_attr, new_line=False)
        self.print(":", _new_line=True)
        with self:
            for i, element in enumerate(node.body):
                if i + 1 != len(node.body):
                    self.visit(element)
                else:
                    self.visit(element, False)
        if node.orelse:
            self.new_line()
            if is_if and type(node.orelse[0]) is _ast.If:
                self.print("el")
                self.visit(node.orelse[0], False)
            else:
                self.print("else:", _new_line=True)
                with self:
                    for i, element in enumerate(node.orelse):
                        if i + 1 != len(node.orelse):
                            self.visit(element)
                        else:
                            self.visit(element, False)

    def _visit_list(self, nodes_list, *, _new_line_at_finish=True):
        for i, node in enumerate(nodes_list):
            self.visit(node, new_line=i + 1 != len(nodes_list) or _new_line_at_finish)

    @staticmethod
    def _ordered_pos_arg_default(pos_only_args, args, defaults):
        assert len(pos_only_args) + len(args) >= len(defaults), (
            len(pos_only_args),
            len(args),
            len(defaults),
        )
        total_args_size = len(pos_only_args) + len(args)
        default_size = len(defaults)
        ordered_only_pos = OrderedDict()
        ordered_args = OrderedDict()
        pos_defaults = 0
        for i, pos_only_arg in enumerate(pos_only_args):
            if i >= total_args_size - default_size:
                ordered_only_pos[pos_only_arg.arg] = [
                    defaults[i - total_args_size + default_size]
                ]
                pos_defaults += 1
            else:
                ordered_only_pos[pos_only_arg.arg] = []
        if pos_defaults:
            for i, arg in enumerate(args):
                ordered_args[arg.arg] = [defaults[i + pos_defaults]]
        else:  # No default argument has been used yet.
            total_defaults = len(args) - len(defaults)
            for i, arg in enumerate(args):
                if i >= total_defaults:
                    ordered_args[arg.arg] = [defaults[i - total_defaults]]
                else:
                    ordered_args[arg.arg] = []
        return ordered_only_pos, ordered_args


class FunctionAndMethodVisitor(ast.NodeVisitor):

    def __init__(self):
        # type: () -> None
        self.callables = set()  # type: Set[ast.FunctionDef, ast.AsyncFunctionDef]
        self._methods = set()  # type: Set[ast.FunctionDef, ast.AsyncFunctionDef]
        self._properties = set()  # type: Set[ast.FunctionDef, ast.AsyncFunctionDef]

    @property
    def functions(self):
        # type: () -> Union[ast.FunctionDef, ast.AsyncFunctionDef]
        return list(self.callables - self._methods - self._properties)

    @property
    def methods(self):
        # type: () -> Union[ast.FunctionDef, ast.AsyncFunctionDef]
        return list(self._methods)

    @property
    def properties(self):
        # type: () -> Union[ast.FunctionDef, ast.AsyncFunctionDef]
        return list(self._properties)

    def visit_ClassDef(self, node):
        # type: (ast.ClassDef) -> ast.AST
        for item in node.body:
            if isinstance(item, ast.FunctionDef) or isinstance(
                item, ast.AsyncFunctionDef
            ):
                if self._has_property_decorator(item):
                    self._properties.add(item)
                else:
                    self._methods.add(item)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # type: (ast.FunctionDef) -> ast.AST
        self.callables.add(node)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        # type: (ast.AsyncFunctionDef) -> ast.AST
        self.callables.add(node)
        return self.generic_visit(node)

    def _has_property_decorator(self, node):
        # type: (Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "property":
                return True
        return False


class FunctionScopedVisitorMixin(ast.NodeVisitor):
    """A visitor which is scoped to a single function.
    This visitor assumes that its `visit` method is called
    on a `ast.FunctionDef`, and it will not examine nested
    functions.
    """

    def __init__(self, *args, **kwargs):
        # type: (List[Any], Dict[str, Any]) -> None
        super(FunctionScopedVisitorMixin, self).__init__(*args, **kwargs)

        # Whether we have passed the initial `FunctionDef` node.
        self.in_function = False

    def visit_Lambda(self, node):
        # type: (ast.Lambda) -> ast.AST
        if not self.in_function:
            self.in_function = True
            return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # type: (ast.FunctionDef) -> ast.AST
        if not self.in_function:
            self.in_function = True
            return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        # type: (ast.AsyncFunctionDef) -> ast.AST
        if not self.in_function:
            self.in_function = True
            return self.generic_visit(node)


def rewrite(file_name: str):
    global file
    file = open("modified_file.py", "a")
    with open(file_name) as f:
        try:
            parsed = ast.parse(f.read(), file_name)  # the AST of the .py file
            Rewrite().visit(parsed)
        except SyntaxError as e:
            raise e
        file.close()


file = None