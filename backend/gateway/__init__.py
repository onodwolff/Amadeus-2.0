"""Gateway package bootstrap helpers.

This package is primarily designed to be imported via the ``backend`` namespace
(e.g. ``backend.gateway.app``).  Some modules, however, still reference the
historical top-level ``gateway`` package.  Attempting to ``pip install
gateway`` fails because that distribution does not exist, resulting in confusing
errors for developers running the code outside of the Docker environment.

To keep backward compatibility we register ``gateway`` as an alias for
``backend.gateway`` so that imports such as ``from gateway.db import models``
resolve correctly without requiring any external package.
"""

from __future__ import annotations

import sys


def _register_alias() -> None:
    """Expose ``gateway`` as an alias for ``backend.gateway``.

    Python places the current module in ``sys.modules`` while it executes this
    file, so we can safely point ``sys.modules['gateway']`` at the same module
    object.  The shared module instance keeps the original ``__path__`` meaning
    any ``gateway.<submodule>`` import will continue to resolve within this
    package tree.
    """

    module = sys.modules[__name__]
    sys.modules.setdefault("gateway", module)


_register_alias()

__all__: list[str] = []
