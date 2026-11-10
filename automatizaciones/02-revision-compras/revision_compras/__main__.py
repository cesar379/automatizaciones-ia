"""Permite ejecutar: python -m revision_compras --empresa <empresa> [--desde AAAA-MM-DD] [--cache]."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
