from re import A

from function_pipes import pipe, pipe_bridge


def test_bridge():
    """
    test the pipe bridge lets you wrap a function that doesn't return a value
    """

    n = None

    def func(v: int):
        nonlocal n
        n = v

    v = pipe(1, lambda x: x + 2, pipe_bridge(func), str)

    assert v == "3", "value has passed through"
    assert n == 3, "function also received the value"
