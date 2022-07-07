from typing import Any


def reveal_type(x: Any):
    return x


from function_pipes import pipe


def test():
    p = pipe(1, lambda x: x + 2, str)
    reveal_type(p)  # T: str


def test_lambda_safe_type():
    p = pipe(1, lambda x: x + 2)
    reveal_type(p)  # T: int


# fmt: off

def test_lambda_error():
    v = str()
    pipe( v, lambda x: x + 2)  # E: Operator "+" not supported for types "str" and "Literal[2]"
# fmt: on
