"""
function-pipe

Functions for pipe syntax in Python.


Version using ParamSpec for Python 3.10 +

Read more at https://github.com/ajparsons/function-pipes

Licence: MIT

"""
# pylint: disable=line-too-long

from ast import (
    Call,
    Lambda,
    Load,
    Name,
    NamedExpr,
    NodeTransformer,
    NodeVisitor,
    Store,
    expr,
    increment_lineno,
    parse,
    walk,
)
from inspect import getsource
from itertools import takewhile
from textwrap import dedent
from typing import Any, Union, Callable, ParamSpec, TypeVar, overload


InputParams = ParamSpec("InputParams")
P = ParamSpec("P")


T = TypeVar("T")


class _LambdaExtractor(NodeTransformer):
    """
    Replace references to the lambda argument with the passed in value
    """

    def __init__(
        self,
        _lambda: Lambda,
        value: Union[expr, Call],
        subsequent_value: Union[expr, Call, None] = None,
    ):
        self._lambda = _lambda
        self.arg_name = self._lambda.args.args[0].arg  # type: ignore
        self.visit_count = 0
        self.value = value
        self.subsequent_value = subsequent_value

    def extract_and_replace(self):
        """
        Return what the lambda does, but replaces
        references to the lambda arg with
        the passed in value
        """
        self.visit(self._lambda.body)
        return self._lambda.body

    def visit_Name(self, node: Name):
        """
        Replace the internal lambda arg reference with the given value
        If a subsequent value given, replace all values after the first with that
        This allows assigning using a walrus in the first value, and then
        using that value without recalculation in the second.
        """
        if node.id == self.arg_name:
            if self.visit_count == 0:
                self.visit_count += 1
                return self.value
            if self.subsequent_value:
                return self.subsequent_value
            else:
                raise ValueError("This lambda contains multiple references to the arg")
        return node


def copy_position(source: expr, destination: expr):
    """
    Copy the position information from one AST node to another
    """
    destination.lineno = source.lineno
    destination.end_lineno = source.end_lineno
    destination.col_offset = source.col_offset
    destination.end_col_offset = source.end_col_offset


class _CountLambdaArgUses(NodeVisitor):
    """
    Count the number of uses of the first argument in the lambda
    in the lambda definition
    """

    def __init__(self, _lambda: Lambda):
        self._lambda = _lambda
        self.arg_name = self._lambda.args.args[0].arg  # type: ignore
        self.uses: int = 0

    def check(self) -> int:
        """
        Get the number of times the arugment is referenced
        """
        self.visit(self._lambda.body)  # type: ignore
        return self.uses

    def visit_Name(self, node: Name):
        """
        Increment the uses count if the name is the given arg
        """
        if node.id == self.arg_name:
            self.uses += 1
        self.generic_visit(node)


class _PipeTransformer(NodeTransformer):
    """
    A NodeTransformer that rewrites the code tree so that all references to replaced with
    a set of nested function calls.

    a = pipe(a,b,c,d)

    becomes

    a = d(c(b(a)))

    This also expands lambdas so that there is no function calling overhead.

    a = pipe(a,b,c,lambda x: x+1)

    becomes:

    a = (c(b(a))) + 1

    Where there are multiple uses of the argument in a lambda,
    a walrus is used to avoid duplication calculations.

    a = pipe(a,b,c,lambda x: x + x + 1)

    becomes:

    a = (var := c(b(a))) + var + 1

    """

    def visit_Call(self, node: Call) -> Any:
        """
        Replace all references to the pipe function with nested function calls.
        """
        if node.func.id == "pipe":  # type: ignore
            value = node.args[0]
            funcs = node.args[1:]

            # unpack the functions into nested calls
            # unless the function is a lambda
            # in which case, the lambda's body
            # needs to be unpacked
            for func in funcs:
                if isinstance(func, Lambda):
                    arg_usage = _CountLambdaArgUses(func).check()
                    if arg_usage == 0:
                        # this will throw an error at build time rather than runtime
                        # but shouldn't be a surprise to typecheckers
                        raise ValueError("This lambda has no arguments.")
                    elif arg_usage == 1:
                        # if the lambda only uses the argument once
                        # can just substitute the arg in the lambda
                        # with the value in the loop
                        # e.g. a = pipe(5, lambda x: x + 1)
                        # becomes a = 5 + 1
                        value = _LambdaExtractor(func, value).extract_and_replace()
                    elif arg_usage > 1:
                        # if the lambda uses the argument more than once
                        # have to assign the value to a variable first
                        # (using a walrus)
                        # and then use the variable in the lambda in subsequent calls.
                        # e.g. a = pipe(5, lambda x: x + x + 1)
                        # becomes a = (var := 5) + var + 1
                        # NamedExpr is how := works behind the scenes.
                        walrus = NamedExpr(
                            target=Name(id="_pipe_temp_var", ctx=Store()), value=value
                        )
                        walrus.lineno = func.lineno
                        copy_position(func, walrus)
                        temp_var = Name(id="_pipe_temp_var", ctx=Load())
                        copy_position(func, temp_var)
                        value = _LambdaExtractor(
                            func, walrus, temp_var
                        ).extract_and_replace()
                else:
                    # if just a function, we're just building a nesting call chain
                    value = Call(func, [value], [])
                copy_position(func, value)
            return value  # type: ignore
        return self.generic_visit(node)


def fast_pipes(func: Callable[P, T]) -> Callable[P, T]:
    """
    Decorator function that replaces references to pipe with
    the direct equivalent of the pipe function.
    """

    # This approach adapted from
    # adapted from https://github.com/robinhilliard/pipes/blob/master/pipeop/__init__.py
    ctx = func.__globals__
    first_line_number = func.__code__.co_firstlineno

    source = getsource(func)

    # AST data structure representing parsed function code
    tree = parse(dedent(source))

    # Fix line and column numbers so that debuggers still work
    increment_lineno(tree, first_line_number - 1)
    source_indent = sum([1 for _ in takewhile(str.isspace, source)]) + 1

    for node in walk(tree):
        if hasattr(node, "col_offset"):
            node.col_offset += source_indent

    # Update name of function or class to compile
    tree.body[0].name += "_fast_pipe"  # type: ignore

    # remove the pipe decorator so that we don't recursively
    # call it again. The AST node for the decorator will be a
    # Call if it had braces, and a Name if it had no braces.
    # The location of the decorator function name in these
    # nodes is slightly different.
    tree.body[0].decorator_list = [  # type: ignore
        d
        for d in tree.body[0].decorator_list  # type: ignore
        if isinstance(d, Call)
        and d.func.id != "fast_pipes"  # type: ignore
        or isinstance(d, Name)
        and d.id != "fast_pipes"
    ]

    # Apply the visit_Call transformation
    tree = _PipeTransformer().visit(tree)

    # now compile the AST into an altered function or class definition
    try:
        code = compile(
            tree,
            filename=(ctx["__file__"] if "__file__" in ctx else "repl"),
            mode="exec",
        )
    except SyntaxError as e:
        # The syntax is rearranged in a way that triggers a starred error correctly
        # Easier to adjust the error here than figure out how to raise it properly
        # in the AST visitor.
        # This is a bit hacky, but it's good enough for now.
        if e.msg == "can't use starred expression here" and (
            e.text and "pipe(" in e.text
        ):
            e.msg = "pipe can't take a starred expression as an argument when fast_pipes is used."
        raise e

    # and execute the definition in the original context so that the
    # decorated function can access the same scopes as the original
    exec(code, ctx)

    # return the modified function or class - original is nevers called
    return ctx[tree.body[0].name]


BridgeType = TypeVar("BridgeType")
InputVal = TypeVar("InputVal")

# Always overridden by the overloads but is
# self consistent in the declared function
stand_in_callable = Union[Callable[..., Any], None]


Out0 = TypeVar("Out0")
Out1 = TypeVar("Out1")
Out2 = TypeVar("Out2")
Out3 = TypeVar("Out3")
Out4 = TypeVar("Out4")
Out5 = TypeVar("Out5")
Out6 = TypeVar("Out6")
Out7 = TypeVar("Out7")
Out8 = TypeVar("Out8")
Out9 = TypeVar("Out9")
Out10 = TypeVar("Out10")
Out11 = TypeVar("Out11")
Out12 = TypeVar("Out12")
Out13 = TypeVar("Out13")
Out14 = TypeVar("Out14")
Out15 = TypeVar("Out15")
Out16 = TypeVar("Out16")
Out17 = TypeVar("Out17")
Out18 = TypeVar("Out18")
Out19 = TypeVar("Out19")


def pipe_bridge(
    func: Callable[[BridgeType], Any]
) -> Callable[[BridgeType], BridgeType]:
    """
    When debugging, you might want to use a function to see
    the current value in the pipe, but examination functions.
    may not return the value to let it continue down the chain.
    This wraps the function so that it does it's job, and then
    returns the original value to conitnue down the chain.
    For instance:
    ```
    bridge(rich.print)
    ```
    Will use the rich library's print function to look at the value,
    but then unlike calling `rich.print` directly in the pipe,
    will return the value to let it continue.
    """

    def _inner(value: BridgeType) -> BridgeType:
        func(value)
        return value

    return _inner


@overload
def pipe(value: InputVal, op0: Callable[[InputVal], Out0], /) -> Out0:
    ...


@overload
def pipe(
    value: InputVal, op0: Callable[[InputVal], Out0], op1: Callable[[Out0], Out1], /
) -> Out1:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    /,
) -> Out2:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    /,
) -> Out3:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    /,
) -> Out4:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    /,
) -> Out5:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    /,
) -> Out6:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    /,
) -> Out7:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    /,
) -> Out8:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    /,
) -> Out9:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    /,
) -> Out10:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    /,
) -> Out11:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    /,
) -> Out12:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    /,
) -> Out13:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    /,
) -> Out14:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    /,
) -> Out15:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    op16: Callable[[Out15], Out16],
    /,
) -> Out16:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    op16: Callable[[Out15], Out16],
    op17: Callable[[Out16], Out17],
    /,
) -> Out17:
    ...


@overload
def pipe(
    value: InputVal,
    op0: Callable[[InputVal], Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    op16: Callable[[Out15], Out16],
    op17: Callable[[Out16], Out17],
    op18: Callable[[Out17], Out18],
    /,
) -> Out18:
    ...


def pipe(value: Any, op0: stand_in_callable = None, op1: stand_in_callable = None, op2: stand_in_callable = None, op3: stand_in_callable = None, op4: stand_in_callable = None, op5: stand_in_callable = None, op6: stand_in_callable = None, op7: stand_in_callable = None, op8: stand_in_callable = None, op9: stand_in_callable = None, op10: stand_in_callable = None, op11: stand_in_callable = None, op12: stand_in_callable = None, op13: stand_in_callable = None, op14: stand_in_callable = None, op15: stand_in_callable = None, op16: stand_in_callable = None, op17: stand_in_callable = None, op18: stand_in_callable = None, op19: stand_in_callable = None, /) -> Any:  # type: ignore
    """
    Pipe takes up to 20 functions and applies them to a value.
    """

    if not op0:
        return value  # fmt: skip

    elif not op1:
        return op0(value)  # fmt: skip

    elif not op2:
        return op1(op0(value))  # fmt: skip

    elif not op3:
        return op2(op1(op0(value)))  # fmt: skip

    elif not op4:
        return op3(op2(op1(op0(value))))  # fmt: skip

    elif not op5:
        return op4(op3(op2(op1(op0(value)))))  # fmt: skip

    elif not op6:
        return op5(op4(op3(op2(op1(op0(value))))))  # fmt: skip

    elif not op7:
        return op6(op5(op4(op3(op2(op1(op0(value)))))))  # fmt: skip

    elif not op8:
        return op7(op6(op5(op4(op3(op2(op1(op0(value))))))))  # fmt: skip

    elif not op9:
        return op8(op7(op6(op5(op4(op3(op2(op1(op0(value)))))))))  # fmt: skip

    elif not op10:
        return op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value))))))))))  # fmt: skip

    elif not op11:
        return op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value)))))))))))  # fmt: skip

    elif not op12:
        return op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value))))))))))))  # fmt: skip

    elif not op13:
        return op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value)))))))))))))  # fmt: skip

    elif not op14:
        return op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value))))))))))))))  # fmt: skip

    elif not op15:
        return op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value)))))))))))))))  # fmt: skip

    elif not op16:
        return op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value))))))))))))))))  # fmt: skip

    elif not op17:
        return op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value)))))))))))))))))  # fmt: skip

    elif not op18:
        return op17(op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value))))))))))))))))))  # fmt: skip

    elif not op19:
        return op18(op17(op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value)))))))))))))))))))  # fmt: skip

    else:
        return op19(op18(op17(op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(value))))))))))))))))))))  # fmt: skip


@overload
def pipeline(op0: Callable[InputParams, Out0], /) -> Callable[InputParams, Out0]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0], op1: Callable[[Out0], Out1], /
) -> Callable[InputParams, Out1]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    /,
) -> Callable[InputParams, Out2]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    /,
) -> Callable[InputParams, Out3]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    /,
) -> Callable[InputParams, Out4]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    /,
) -> Callable[InputParams, Out5]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    /,
) -> Callable[InputParams, Out6]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    /,
) -> Callable[InputParams, Out7]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    /,
) -> Callable[InputParams, Out8]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    /,
) -> Callable[InputParams, Out9]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    /,
) -> Callable[InputParams, Out10]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    /,
) -> Callable[InputParams, Out11]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    /,
) -> Callable[InputParams, Out12]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    /,
) -> Callable[InputParams, Out13]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    /,
) -> Callable[InputParams, Out14]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    /,
) -> Callable[InputParams, Out15]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    op16: Callable[[Out15], Out16],
    /,
) -> Callable[InputParams, Out16]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    op16: Callable[[Out15], Out16],
    op17: Callable[[Out16], Out17],
    /,
) -> Callable[InputParams, Out17]:
    ...


@overload
def pipeline(
    op0: Callable[InputParams, Out0],
    op1: Callable[[Out0], Out1],
    op2: Callable[[Out1], Out2],
    op3: Callable[[Out2], Out3],
    op4: Callable[[Out3], Out4],
    op5: Callable[[Out4], Out5],
    op6: Callable[[Out5], Out6],
    op7: Callable[[Out6], Out7],
    op8: Callable[[Out7], Out8],
    op9: Callable[[Out8], Out9],
    op10: Callable[[Out9], Out10],
    op11: Callable[[Out10], Out11],
    op12: Callable[[Out11], Out12],
    op13: Callable[[Out12], Out13],
    op14: Callable[[Out13], Out14],
    op15: Callable[[Out14], Out15],
    op16: Callable[[Out15], Out16],
    op17: Callable[[Out16], Out17],
    op18: Callable[[Out17], Out18],
    /,
) -> Callable[InputParams, Out18]:
    ...


def pipeline(op0: Callable[InputParams, Out0], op1: Union[Callable[[Out0], Out1], None] = None, op2: Union[Callable[[Out1], Out2], None] = None, op3: Union[Callable[[Out2], Out3], None] = None, op4: Union[Callable[[Out3], Out4], None] = None, op5: Union[Callable[[Out4], Out5], None] = None, op6: Union[Callable[[Out5], Out6], None] = None, op7: Union[Callable[[Out6], Out7], None] = None, op8: Union[Callable[[Out7], Out8], None] = None, op9: Union[Callable[[Out8], Out9], None] = None, op10: Union[Callable[[Out9], Out10], None] = None, op11: Union[Callable[[Out10], Out11], None] = None, op12: Union[Callable[[Out11], Out12], None] = None, op13: Union[Callable[[Out12], Out13], None] = None, op14: Union[Callable[[Out13], Out14], None] = None, op15: Union[Callable[[Out14], Out15], None] = None, op16: Union[Callable[[Out15], Out16], None] = None, op17: Union[Callable[[Out16], Out17], None] = None, op18: Union[Callable[[Out17], Out18], None] = None, op19: Union[Callable[[Out18], Out19], None] = None, /) -> Callable[InputParams, Any]:  # type: ignore
    """
    Pipeline takes up to 20 functions and composites them into a single function.
    """

    if not op1:

        def _inner0(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out0:
            return op0(*args, **kwargs)  # fmt: skip

        return _inner0

    elif not op2:

        def _inner1(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out1:
            return op1(op0(*args, **kwargs))  # fmt: skip

        return _inner1

    elif not op3:

        def _inner2(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out2:
            return op2(op1(op0(*args, **kwargs)))  # fmt: skip

        return _inner2

    elif not op4:

        def _inner3(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out3:
            return op3(op2(op1(op0(*args, **kwargs))))  # fmt: skip

        return _inner3

    elif not op5:

        def _inner4(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out4:
            return op4(op3(op2(op1(op0(*args, **kwargs)))))  # fmt: skip

        return _inner4

    elif not op6:

        def _inner5(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out5:
            return op5(op4(op3(op2(op1(op0(*args, **kwargs))))))  # fmt: skip

        return _inner5

    elif not op7:

        def _inner6(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out6:
            return op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))  # fmt: skip

        return _inner6

    elif not op8:

        def _inner7(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out7:
            return op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))  # fmt: skip

        return _inner7

    elif not op9:

        def _inner8(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out8:
            return op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))))  # fmt: skip

        return _inner8

    elif not op10:

        def _inner9(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out9:
            return op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))))  # fmt: skip

        return _inner9

    elif not op11:

        def _inner10(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out10:
            return op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))))))  # fmt: skip

        return _inner10

    elif not op12:

        def _inner11(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out11:
            return op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))))))  # fmt: skip

        return _inner11

    elif not op13:

        def _inner12(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out12:
            return op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))))))))  # fmt: skip

        return _inner12

    elif not op14:

        def _inner13(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out13:
            return op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))))))))  # fmt: skip

        return _inner13

    elif not op15:

        def _inner14(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out14:
            return op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))))))))))  # fmt: skip

        return _inner14

    elif not op16:

        def _inner15(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out15:
            return op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))))))))))  # fmt: skip

        return _inner15

    elif not op17:

        def _inner16(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out16:
            return op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))))))))))))  # fmt: skip

        return _inner16

    elif not op18:

        def _inner17(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out17:
            return op17(op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))))))))))))  # fmt: skip

        return _inner17

    elif not op19:

        def _inner18(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out18:
            return op18(op17(op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs)))))))))))))))))))  # fmt: skip

        return _inner18

    else:

        def _inner19(*args: InputParams.args, **kwargs: InputParams.kwargs) -> Out19:
            return op19(op18(op17(op16(op15(op14(op13(op12(op11(op10(op9(op8(op7(op6(op5(op4(op3(op2(op1(op0(*args, **kwargs))))))))))))))))))))  # fmt: skip

        return _inner19


def arbitary_length_pipe(value: Any, *funcs: Callable[[Any], Any]) -> Any:
    """
    Pipe that takes an arbitary amount of functions.
    """
    for func in funcs:
        value = func(value)
    return value
