"""
Typed python equivalent for R pipes.
"""

__version__ = "0.1.2"

import sys

if sys.version_info >= (3, 10):
    from .with_paramspec.function_pipes import *
else:
    from .without_paramspec.function_pipes import *
