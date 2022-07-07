import random
from typing import Any, Callable

from function_pipes import pipe

pipe_allowed_size = 20


def basic_pipe(value: Any, *funcs: Callable[[Any], Any]) -> Any:
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


def times_ten(value: Any) -> Any:
    """
    Multiplies a value by ten.
    """
    return value * 10


def divide_by_two(value: Any) -> Any:
    """
    Divides a value by two.
    """
    return value / 2


def test_basic_pipe():
    """
    Test basic pipe function.
    """
    assert basic_pipe(1, add_one, times_ten, divide_by_two) == 10
    assert basic_pipe(1, add_one, times_ten) == 20
    assert basic_pipe(1, add_one) == 2
    assert basic_pipe(1) == 1


def test_equiv_function():
    """
    test the pipe function works the same as the basic_pipe function
    """
    # list of functions to apply
    funcs = [add_one, times_ten, divide_by_two]

    def get_random_function_from_funcs():
        """
        Get a random function from the list of functions.
        """
        return random.choice(funcs)

    for n in range(1, pipe_allowed_size):
        # a list n long of random functions
        random_funcs = [get_random_function_from_funcs() for _ in range(n)]
        # get a random number
        random_number = random.randint(0, 100)
        # apply the functions to the number
        result = pipe(random_number, *random_funcs)
        # apply the functions to the number
        result_basic = basic_pipe(random_number, *random_funcs)
        # assert the results are the same
        assert result == result_basic, f"mismatch for {n}"
