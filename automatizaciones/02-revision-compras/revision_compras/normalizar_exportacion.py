"""Convierte la exportación «Exportar líneas» de compras de Holded al modelo neutro.

Sirve cuando no hay clave de API: en Holded, Compras > Facturas > Acciones >
Exportar líneas genera un Excel con una fila por línea de factura. Limitaciones
de ese archivo, que el informe explica:

- No indica el tipo de documento: se considera abono todo documento con total
  negativo, así que no se puede detectar una rectificativa registrada como compra.
- No incluye notas ni los contactos completos: el NIF sale de la columna
  «Contact ID» y cada par nombre + NIF se trata como una ficha de proveedor.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from .modelo import ABONO, CERO, COMPRA, Contacto, Documento, Linea
from .texto import a_decimal, normalizar_nif, normalizar_nombre

# Nombres de columna en inglés y en español (según el idioma de la cuenta).
COLUMNAS = {
    "numero": ("invoice num", "num", "numero", "número", "numero factura", "número factura", "nº factura"),
    "fecha": ("date", "fecha"),
    "vencimiento": ("due date", "vencimiento", "fecha vencimiento"),
    "descripcion": ("description", "descripcion", "descripción"),
    "borrador": ("draft", "borrador"),
    "proveedor": ("contact", "contacto", "proveedor"),
    "nif": ("contact id", "nif", "cif", "id contacto"),
    "sku": ("sku",),
    "concepto": ("item", "concepto", "producto"),
    "unidades": ("units", "unidades", "cantidad"),
    "subtotal": ("subtotal",),
    "impuesto": ("tax", "impuesto", "iva"),
    "total_impuestos": ("total tax", "total impuestos", "total iva"),
    "total": ("total",),
}
OBLIGATORIAS = ("numero", "fecha", "proveedor", "subtotal", "total")


class ErrorExportacion(Exception):
    """El archivo no tiene el formato de la exportación de líneas de Holded."""


def _clave(texto) -> str:
    return " ".join(str(texto or "").strip().lower().split())


def _indices(cabecera) -> dict[str, int]:
    posiciones = {_clave(c): i for i, c in enumerate(cabecera) if c not in (None, "")}
    indices = {}
    for campo, alias in COLUMNAS.items():
        for a in alias:
            if a in posiciones:
                indices[campo] = posiciones[a]
                break
    return indices


def _a_fecha(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def leer_filas(ruta: Path) -> list[dict]:
    """Devuelve una lista de diccionarios campo -> valor, una por línea de factura."""
    try:
        libro = load_workbook(ruta, read_only=True, data_only=True)
    except Exception as e:  # archivo inexistente, dañado o que no es xlsx
        raise ErrorExportacion(f"No se pudo abrir {ruta} ({type(e).__name__}).") from None
    try:
        filas = list(libro.worksheets[0].iter_rows(values_only=True))
    finally:
        libro.close()
    for n, fila in enumerate(filas[:20]):
        indices = _indices(fila)
        if all(c in indices for c in OBLIGATORIAS):
            break
    else:
        raise ErrorExportacion(
            f"{ruta.name} no parece una exportación de líneas de compras de Holded "
            f"(no se encuentran las columnas {', '.join(OBLIGATORIAS)})."
        )
    resultado = []
    for fila in filas[n + 1:]:
        if not fila or all(v in (None, "") for v in fila):
            continue
        datos = {campo: (fila[i] if i < len(fila) else None) for campo, i in indices.items()}
        if datos.get("proveedor") in (None, "") and _a_fecha(datos.get("fecha")) is None:
            continue  # filas vacías y el pie «Report powered automatically by Holded»
        resultado.append(datos)
    return resultado


def _id_proveedor(nombre: str, nif: str) -> str:
    return f"{normalizar_nif(nif)}|{normalizar_nombre(nombre)}"


def normalizar_filas(filas: list[dict]) -> tuple[list[Documento], list[Contacto]]:
    grupos: OrderedDict[tuple, list[dict]] = OrderedDict()
    for f in filas:
        if _clave(f.get("borrador")) in ("si", "sí", "yes", "true", "1"):
            continue  # los borradores no son compras registradas
        nombre, nif = _texto(f.get("proveedor")), _texto(f.get("nif"))
        clave = (_texto(f.get("numero")), _id_proveedor(nombre, nif), _a_fecha(f.get("fecha")))
        grupos.setdefault(clave, []).append(f)

    documentos, contactos = [], OrderedDict()
    for (numero, proveedor_id, fecha), lineas in grupos.items():
        primera = lineas[0]
        nombre, nif = _texto(primera.get("proveedor")), _texto(primera.get("nif"))
        contactos.setdefault(proveedor_id, Contacto(
            id=proveedor_id, nombre=nombre, nif=nif, tipo="supplier", es_proveedor=True,
        ))
        total = sum((a_decimal(l.get("total")) for l in lineas), CERO)
        subtotal = sum((a_decimal(l.get("subtotal")) for l in lineas), CERO)
        impuestos = sum((a_decimal(l.get("total_impuestos")) for l in lineas), CERO)
        documentos.append(Documento(
            id=f"{numero}|{proveedor_id}|{fecha.isoformat() if fecha else ''}",
            tipo=ABONO if total < 0 else COMPRA,
            fecha=fecha,
            numero=numero,
            proveedor_id=proveedor_id,
            proveedor_nombre=nombre,
            descripcion=_texto(primera.get("descripcion")),
            total=total,
            subtotal=subtotal,
            impuestos=impuestos,
            lineas=tuple(_linea(l) for l in lineas),
        ))
    return documentos, list(contactos.values())


def _linea(fila: dict) -> Linea:
    unidades = a_decimal(fila.get("unidades"))
    subtotal = a_decimal(fila.get("subtotal"))
    precio = subtotal / unidades if unidades else subtotal
    impuesto = a_decimal(fila.get("impuesto"))
    impuesto_pct = (impuesto / subtotal * 100).quantize(Decimal("0.01")) if subtotal else CERO
    return Linea(
        nombre=_texto(fila.get("concepto")),
        sku=_texto(fila.get("sku")),
        precio=precio,
        unidades=unidades,
        impuesto_pct=impuesto_pct,
    )


def leer_exportacion(ruta: Path) -> tuple[list[Documento], list[Contacto]]:
    return normalizar_filas(leer_filas(Path(ruta)))


NOTAS_EXPORTACION = (
    "Datos tomados de la exportación de líneas de Holded, no de la API: se considera abono todo documento con "
    "total negativo, así que no se detectan rectificativas registradas como compra normal.",
    "La exportación no incluye las notas de las compras ni las fichas completas de contactos: el NIF sale de la "
    "columna «Contact ID» y cada par nombre + NIF cuenta como una ficha de proveedor.",
)
