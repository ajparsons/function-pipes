import pytest
from function_pipes import fast_pipes, pipe

funcs = [str, str, str]


def test_starred_error():
    with pytest.raises(
        SyntaxError,
        match="pipe can't take a starred expression as an argument when fast_pipes is used.",
    ):

        @fast_pipes
        def test():
            return pipe(1, *funcs)

        t = test()
