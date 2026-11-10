"""Modelo neutro de datos, independiente del ERP de origen.

Las reglas trabajan solo con estas clases. Para usar otro ERP (o un archivo
exportado) basta con escribir un normalizador que produzca estos objetos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

COMPRA = "compra"
ABONO = "abono"

ALTA = "alta"
MEDIA = "media"
BAJA = "baja"
ORDEN_PRIORIDAD = {ALTA: 0, MEDIA: 1, BAJA: 2}

CERO = Decimal("0")


@dataclass(frozen=True)
class Linea:
    nombre: str = ""
    descripcion: str = ""
    sku: str = ""
    precio: Decimal = CERO          # precio unitario sin IVA, antes del descuento
    unidades: Decimal = CERO
    descuento_pct: Decimal = CERO   # % de descuento de la línea
    impuesto_pct: Decimal = CERO

    @property
    def precio_neto(self) -> Decimal:
        """Precio unitario con el descuento de línea aplicado, sin IVA."""
        return self.precio * (Decimal("1") - self.descuento_pct / Decimal("100"))


@dataclass(frozen=True)
class Documento:
    id: str
    tipo: str                       # COMPRA o ABONO
    fecha: date | None
    numero: str = ""
    proveedor_id: str = ""
    proveedor_nombre: str = ""
    descripcion: str = ""
    notas: str = ""
    total: Decimal = CERO
    subtotal: Decimal = CERO
    impuestos: Decimal = CERO
    moneda: str = "EUR"
    estado: str = ""
    lineas: tuple[Linea, ...] = ()
    origen_id: str = ""             # documento del que procede (p. ej. compra original de un abono)

    @property
    def es_abono(self) -> bool:
        return self.tipo == ABONO

    @property
    def referencia(self) -> str:
        """Texto para identificar el documento en el informe."""
        return self.numero or f"(sin número, id {self.id})"


@dataclass(frozen=True)
class Contacto:
    id: str
    nombre: str = ""
    nif: str = ""
    tipo: str = ""                  # supplier, creditor, client...
    es_proveedor: bool = False


@dataclass(frozen=True)
class Aviso:
    prioridad: str                  # ALTA, MEDIA o BAJA
    tipo: str
    proveedor: str
    documentos: str
    fecha: date | None
    importe: Decimal
    detalle: str
    accion: str
    ids: tuple[str, ...] = field(default=(), compare=False)
