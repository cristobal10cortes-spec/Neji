"""Arranque de NejiPOS.exe cuando el código va compilado con Nuitka (ver NejiPOS.spec): escritorio y el
paquete neji son módulos nativos (.pyd), y este archivo solo los pone en marcha."""

import sys

import escritorio

sys.exit(escritorio.main())
