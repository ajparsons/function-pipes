from typing import Any

from function_pipes import fast_pipes, pipe


def add_one(value: Any) -> Any:
    """
    Adds one to a value.
    """
    return value + 1


def times_twelve(value: Any) -> Any:
    """
    Multiplies a value by 12.
    """
    return value * 12


@fast_pipes
def pipe_version():
    return pipe(12, add_one, times_twelve, times_twelve, add_one)


def raw_version():
    return add_one(times_twelve(times_twelve(add_one(12))))


def test_pipe_equiv():
    assert (
        pipe_version() == raw_version()
    ), "fast_pipe version is not equiv to basic version"


@fast_pipes
def pipe_version_with_lambda():
    return pipe(12, add_one, times_twelve, times_twelve, add_one, lambda x: x / 2)


def raw_version_with_function():
    return add_one(times_twelve(times_twelve(add_one(12)))) / 2


def test_pipe_lambda_equiv():
    assert (
        pipe_version() == raw_version()
    ), "fast_pipe version is not equivalent to raw version when lambda is used"


def pipe_version_with_lambda_used_more_than_once():
    return pipe(12, add_one, times_twelve, times_twelve, add_one, lambda x: x + x + 2)


def raw_version_with_function_used_more_than_once():
    v = add_one(times_twelve(times_twelve(add_one(12))))
    return v + v + 2


def test_pipe_lambda_equiv_multiple():
    assert (
        pipe_version_with_lambda_used_more_than_once()
        == raw_version_with_function_used_more_than_once()
    ), "fast_pipe version is not equivalent to raw version when lambda value is used multiple times"
