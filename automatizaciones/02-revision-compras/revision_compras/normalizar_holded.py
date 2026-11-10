"""Convierte el JSON de Holded (v2 y, por tolerancia, v1) al modelo neutro.

Se aceptan varios nombres para cada campo porque la v1 usa camelCase y parte
de su esquema no está documentado oficialmente.
"""

from __future__ import annotations

from .modelo import ABONO, COMPRA, Contacto, Documento, Linea
from .texto import ZONA_HORARIA, a_decimal, a_fecha

TIPOS_PROVEEDOR = {"supplier", "creditor", "proveedor", "acreedor"}


def _primero(datos: dict, *claves, defecto=None):
    """Devuelve el primer valor no vacío entre varias claves posibles."""
    for clave in claves:
        valor = datos.get(clave)
        if valor not in (None, "", [], {}):
            return valor
    return defecto


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, list):
        partes = []
        for v in valor:
            if isinstance(v, dict):
                partes.append(str(_primero(v, "description", "desc", "text", "name", "title", defecto="")))
            else:
                partes.append(str(v))
        return " | ".join(p for p in partes if p)
    if isinstance(valor, dict):
        return str(_primero(valor, "description", "desc", "text", "name", defecto=""))
    return str(valor).strip()


def linea(datos: dict) -> Linea:
    return Linea(
        nombre=_texto(_primero(datos, "name", "concept", "nombre")),
        descripcion=_texto(_primero(datos, "description", "desc", "descripcion")),
        sku=_texto(_primero(datos, "sku", "SKU", "code")),
        precio=a_decimal(_primero(datos, "price", "unit_price", "unitPrice", "precio")),
        unidades=a_decimal(_primero(datos, "units", "quantity", "qty", "unidades")),
        descuento_pct=a_decimal(_primero(datos, "discount", "descuento")),
        impuesto_pct=a_decimal(_primero(datos, "tax", "iva")),
    )


def documento(datos: dict, tipo: str, zona_horaria: str = ZONA_HORARIA) -> Documento:
    """``tipo`` es COMPRA o ABONO, según el recurso del que se ha leído.

    ``zona_horaria`` sirve para pasar a fecha los timestamps Unix de la v1.
    """
    if tipo not in (COMPRA, ABONO):
        raise ValueError(f"Tipo de documento desconocido: {tipo}")
    lineas_crudas = _primero(datos, "lines", "products", "items", defecto=[]) or []
    origen = datos.get("from")
    origen_id = ""
    if isinstance(origen, dict):
        origen_id = str(_primero(origen, "id", "docId", defecto="") or "")
    contacto = _primero(datos, "contact_id", "contactId", "contact")
    if isinstance(contacto, dict):
        contacto = _primero(contacto, "id", "_id")
    return Documento(
        id=str(_primero(datos, "id", "_id", defecto="")),
        tipo=tipo,
        fecha=a_fecha(_primero(datos, "date", "fecha"), zona_horaria),
        numero=_texto(_primero(datos, "document_number", "docNumber", "number", "numero")),
        proveedor_id=str(contacto or ""),
        proveedor_nombre=_texto(_primero(datos, "contact_name", "contactName", "proveedor")),
        descripcion=_texto(_primero(datos, "description", "desc", "descripcion")),
        notas=_texto(_primero(datos, "notes", "notas")),
        total=a_decimal(_primero(datos, "total")),
        subtotal=a_decimal(_primero(datos, "subtotal")),
        impuestos=a_decimal(None if isinstance(datos.get("tax"), (list, dict)) else datos.get("tax")),
        moneda=str(_primero(datos, "currency", defecto="EUR")).upper(),
        estado=str(_primero(datos, "status", defecto="") or ""),
        lineas=tuple(linea(l) for l in lineas_crudas if isinstance(l, dict)),
        origen_id=origen_id,
    )


def contacto(datos: dict) -> Contacto:
    tipo = str(_primero(datos, "type", "tipo", defecto="") or "").lower()
    ficha_proveedor = _primero(datos, "supplier_record", "supplierRecord")
    tiene_ficha_proveedor = bool(
        isinstance(ficha_proveedor, dict) and _primero(ficha_proveedor, "num", "name")
    )
    return Contacto(
        id=str(_primero(datos, "id", "_id", defecto="")),
        nombre=_texto(_primero(datos, "name", "trade_name", "tradeName", "nombre")),
        nif=_texto(_primero(datos, "code", "vat_number", "vatnumber", "vatNumber", "nif", "cif")),
        tipo=tipo,
        es_proveedor=tipo in TIPOS_PROVEEDOR or tiene_ficha_proveedor,
    )


def normalizar(compras: list[dict], abonos: list[dict], contactos: list[dict], zona_horaria: str = ZONA_HORARIA):
    """Devuelve (documentos, contactos) en el modelo neutro."""
    documentos = (
        [documento(c, COMPRA, zona_horaria) for c in compras]
        + [documento(a, ABONO, zona_horaria) for a in abonos]
    )
    return documentos, [contacto(c) for c in contactos]
