"""
Run meta tests on package (apply to muliple packages)

"""
import timeit
from typing import Any, Callable

from function_pipes import fast_pipes, pipe


def base_pipe(value: Any, *funcs: Callable[[Any], Any]) -> Any:
    """
    A basic pipe function.
    """
    for func in funcs:
        value = func(value)
    return value


def add_one(value: Any) -> Any:
    """
    Adds one to a value.
    """
    return value + 1


def times_12(value: Any) -> Any:
    """
    Multiplies a value by 12.
    """
    return value * 12


def func_raw():
    return add_one(times_12(times_12(add_one(12))))


def func_basic():
    return base_pipe(12, add_one, times_12, times_12, add_one)


def func_pipe():
    return pipe(12, add_one, times_12, times_12, add_one)


@fast_pipes
def func_fast():
    return pipe(12, add_one, times_12, times_12, add_one)


def get_speed(func: Callable[..., Any]):
    return min(
        timeit.repeat(
            func,
            number=100000,
            repeat=100,
        )
    )


def test_speed():
    raw_result = get_speed(func_raw)
    fast_result = get_speed(func_fast)
    pipe_result = get_speed(func_pipe)
    basic_result = get_speed(func_basic)

    assert raw_result < pipe_result, "Raw should be faster than pipe"
    assert fast_result < pipe_result, "Fast should be faster than pipe"
    assert pipe_result < basic_result, "Pipe should be faster than basic"
