"""Constructores de datos 100 % ficticios para las pruebas.

Nombres y NIF inventados: no corresponden a ninguna empresa real.
"""

from datetime import date
from decimal import Decimal

from revision_compras.modelo import ABONO, COMPRA, Contacto, Documento, Linea

NIF_PROPIO = "B00000099"
_contador = [0]


def _id() -> str:
    _contador[0] += 1
    return f"{_contador[0]:024x}"


def d(texto: str) -> date:
    return date.fromisoformat(texto)


def linea(nombre="Producto ficticio", precio="10", unidades="1", descuento="0", sku=""):
    return Linea(
        nombre=nombre,
        sku=sku,
        precio=Decimal(precio),
        unidades=Decimal(unidades),
        descuento_pct=Decimal(descuento),
        impuesto_pct=Decimal("21"),
    )


def compra(fecha, total, numero="", proveedor="P1", nombre="Proveedor Ejemplo SL",
           descripcion="", notas="", lineas=(), estado="pending", tipo=COMPRA):
    return Documento(
        id=_id(),
        tipo=tipo,
        fecha=d(fecha),
        numero=numero,
        proveedor_id=proveedor,
        proveedor_nombre=nombre,
        descripcion=descripcion,
        notas=notas,
        total=Decimal(str(total)),
        lineas=tuple(lineas),
        estado=estado,
    )


def abono(fecha, total, numero="", proveedor="P1", nombre="Proveedor Ejemplo SL", descripcion="", lineas=()):
    return compra(fecha, total, numero, proveedor, nombre, descripcion, lineas=lineas, tipo=ABONO)


def contacto(id_, nombre="Proveedor Ejemplo SL", nif="B00000001", tipo="supplier"):
    return Contacto(id=id_, nombre=nombre, nif=nif, tipo=tipo, es_proveedor=tipo in ("supplier", "creditor"))
