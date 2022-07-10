# function-pipes

[![PyPI](https://img.shields.io/pypi/v/function-pipes.svg)](https://pypi.org/project/function-pipes/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/inkleby/function-pipes/blob/main/LICENSE.md)
[![Copy and Paste](https://img.shields.io/badge/Copy%20%2B%20Paste%3F-yes!-blue)](#install)

Fast, type-hinted python equivalent for R pipes.

This decorator only relies on the standard library, so can just be copied into a project as a single file.

# Why is this needed?

Various languages have versions of a 'pipe' syntax, where a value can be passed through a succession of different functions before returning the final value. 

This means you can avoid syntax like the below, where the sequence is hard to read (especially if extra arguments are introduced).

```python
a = c(b(a(value)))
```

In Python, there is not a good built-in way of doing this, and other attempts at a pipe do not play nice with type hinting. 

This library has a very simple API, and does the fiddly bits behind the scenes to keep the pipe fast. 

## The pipe

There is a `pipe`, function which expects a value and then a list of callables.

```python
from function_pipes import pipe

value = pipe(5, lambda x: x + 2, str)
value == "7"

```

## No special form for extra arguments, small special case for functions that don't return a value

There is no bespoke syntax for passing in extra arguments or moving where the pipe's current value is placed - just use a lambda. This is a well understood approach, that is compatible with type hinting. In the above, `value` will be recognised as a string, but the x is understood as an int. 

There is a small bit of bespoke syntax for when you want to pass something through a function, but that function doesn't return the result to the next function. Here the `pipe_bridge` function will wrap another function, pass the function into it, and continue onwards. The following will print `7`, before passing the value on. 

```python
from function_pipes import pipe, pipe_bridge

value = pipe(5, lambda x: x + 2, pipe_bridge(print), str)
value == "7"

```

## Merging functions to use later

There is also a `pipeline`, which given a set of functions will return a function which a value can be passed into. Where possible based on other hints, this will hint the input and output variable types.

```python
from function_pipes import pipeline

func = pipeline(lambda x: x + 2, str)
func(5) == "7"

```

## Optimising use of pipes

There's work behind the scenes to minimise the overhead of using the pipe, but it is still adding a function call. If you want the readability of the pipe *and* the speed of the native ugly approach you can use the `@fast_pipes` decorator. This rewrites the function it is called on to expand out the pipe and any lambdas into the fastest native equivalent. 

e.g. These two functions should have equivalent AST trees:

```python

@fast_pipes
def function_that_has_a_pipe(v: int) -> str:
    value = pipe(v, a, lambda x: b(x, foo="other_input"), c)
    return pipe
```

```python
def function_that_has_a_pipe(v: int) -> str:
    value = c(b(a(v),foo="other_input"))
    return pipe
```

This version of the function is solving three versions of the same puzzle at the same time:

* The type hinting is unpacking the structure when it is being written.
* The pipe function solves the problem in standard python.
* The fast_pipes decorator is rewriting the AST tree to get the same outcome faster.

But to the user, it all looks the same - pipes!

There is a limit of 20 functions that can be passed to a pipe or pipeline. If you *really* want to do more, you could chain multiple pipelines together.

## Install

You can install from pip: `python -m pip install function-pipes`

Or you can copy the module directly into your projects.

* For python 3.10+: [with_paramspec/function_pipes.py](https://github.com/ajparsons/function-pipes/src/function_pipes/with_paramspec/function_pipes.py)
* For python 3.8, 3.9: [without_paramspec/function_pipes.py](https://github.com/ajparsons/function-pipes/src/function_pipes/without_paramspec/function_pipes.py)

## Development

This project comes with a Dockerfile and devcontainer that should get a good environment set up. 

The actual code is generated from `src/function_pipes/pipes.jinja-py` using jinja to generate the code and the seperate versions with and without use of paramspec.

Use `make` to regenerate the files. The number of allowed arguments is specified in `Makefile`.

There is a test suite that does checks for equivalence between this syntax and the raw syntax, as well as checking that fast_pipes and other optimisations are faster. 

This can be run with `script/test`.