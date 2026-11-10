"""Normalización de textos y del JSON de Holded al modelo neutro (datos ficticios)."""

from datetime import date
from decimal import Decimal

from revision_compras import normalizar_holded as nh
from revision_compras.modelo import ABONO, COMPRA
from revision_compras.texto import (
    a_decimal,
    a_fecha,
    contiene_palabra,
    empieza_por_palabra,
    es_numero_generico,
    euros,
    importe_moneda,
    mismo_numero_documento,
    normalizar_nif,
    normalizar_nombre,
    normalizar_numero_documento,
)


def test_numero_documento():
    assert normalizar_numero_documento("F-0001") == normalizar_numero_documento("f 1") == "F1"
    assert normalizar_numero_documento("2026/0007") == normalizar_numero_documento("2026-7")
    assert normalizar_numero_documento("") == ""
    assert normalizar_numero_documento("000") == "0"


def test_numero_documento_mes_y_secuencia_no_se_confunden():
    # Antes "01/12" y "11/02" daban los dos "112"
    assert normalizar_numero_documento("01/12") == "1|12"
    assert normalizar_numero_documento("11/02") == "11|2"
    assert not mismo_numero_documento("01/12", "11/02")
    assert not mismo_numero_documento("1/12", "11/2")


def test_mismo_numero_con_y_sin_separador():
    assert mismo_numero_documento("F2026-0001", "F20260001")
    assert mismo_numero_documento("F-0001", "f 1")
    assert mismo_numero_documento("FAC 2026/0007", "fac-2026-7")
    assert not mismo_numero_documento("F2026-0001", "G20260001")
    assert not mismo_numero_documento("A1-2", "A12")       # pocas cifras: no se fuerza


def test_numeros_genericos_nunca_coinciden():
    for numero in ("S/N", "s-n", "SN", "Ticket", "0", "000", "", "sin número"):
        assert es_numero_generico(numero), numero
    assert not mismo_numero_documento("S/N", "s-n")
    assert not mismo_numero_documento("Ticket", "TICKET")
    assert not es_numero_generico("F-1")


def test_nombre_sin_forma_juridica_ni_puntuacion():
    esperado = "proveedor ejemplo"
    for nombre in ("Proveedor Ejemplo, S.L.", "PROVEEDOR  EJEMPLO SL", "Proveedor Ejemplo S. L. U.",
                   "Proveedor Ejemplo Sociedad Limitada", "Proveedor Ejémplo, SLU"):
        assert normalizar_nombre(nombre) == esperado, nombre
    assert normalizar_nombre("Suministros Inventados, S.A.") == "suministros inventados"


def test_nif():
    assert normalizar_nif("b-00000001") == "B00000001"
    assert normalizar_nif("ES B00000001") == "B00000001"
    assert normalizar_nif(None) == ""
    assert normalizar_nif("DE123456789") == "DE123456789"     # NIF-IVA extranjero


def test_nif_de_relleno_cuenta_como_vacio():
    for nif in ("N/A", "-", "00000000", "B00000000", "X", "0", "NIF", "123"):
        assert normalizar_nif(nif) == "", nif


def test_importes_y_fechas():
    assert a_decimal("121.00") == Decimal("121.00")
    assert a_decimal("1.234,56") == Decimal("1234.56")
    assert a_decimal("1,234.56") == Decimal("1234.56")
    assert a_decimal(None) == 0 and a_decimal("abc") == 0
    assert a_fecha("2026-01-15") == date(2026, 1, 15)
    assert a_fecha("2026-01-15T10:30:00Z") == date(2026, 1, 15)
    assert a_fecha(1768435200) == date(2026, 1, 15)          # Unix en segundos (v1)
    assert a_fecha(1768431600) == date(2026, 1, 15)          # 00:00 del 15/01 en Madrid (23:00 UTC del 14)
    assert a_fecha(1768431600, "UTC") == date(2026, 1, 14)
    assert a_fecha("1768431600") == date(2026, 1, 15)
    assert a_fecha("15/01/2026") == date(2026, 1, 15)
    assert euros(Decimal("-1234.5")) == "-1.234,50 €"
    assert importe_moneda(Decimal("1000"), "usd") == "1.000,00 USD"
    assert importe_moneda(Decimal("1000"), "EUR") == "1.000,00 €"


def test_contiene_palabra_al_inicio_de_palabra():
    assert contiene_palabra("Se va a DEVOLVER", ["devolver"]) == "devolver"
    assert contiene_palabra("Devoluciones pendientes", ["devolucion"]) == "devolucion"
    assert contiene_palabra("Película de terror", ["error"]) is None
    assert contiene_palabra("esto no se hace así", ["no se hace"]) == "no se hace"


def test_empieza_por_palabra():
    assert empieza_por_palabra("Presupuesto reforma oficina", ["presupuesto"]) == "presupuesto"
    assert empieza_por_palabra("  - PROFORMA 12", ["proforma"]) == "proforma"
    assert empieza_por_palabra("Reforma local según presupuesto nº 45 aceptado", ["presupuesto"]) is None


COMPRA_V2 = {
    "id": "000000000000000000000001",
    "document_number": "F-0001",
    "contact_id": "0000000000000000000000c1",
    "contact_name": "Proveedor Ejemplo SL",
    "description": "Material de prueba",
    "date": "2026-01-15",
    "due_date": "2026-02-15",
    "subtotal": "100.00",
    "discount": "0",
    "tax": "21.00",
    "total": "121.00",
    "currency": "eur",
    "status": "pending",
    "lines": [{"name": "Artículo ficticio", "sku": "ART-1", "price": "50.00", "units": "2",
               "discount": "10", "tax": "21", "taxes": ["x"]}],
}


def test_compra_v2():
    doc = nh.documento(COMPRA_V2, COMPRA)
    assert doc.tipo == COMPRA and doc.numero == "F-0001"
    assert doc.proveedor_id == "0000000000000000000000c1"
    assert doc.total == Decimal("121.00") and doc.impuestos == Decimal("21.00")
    assert doc.fecha == date(2026, 1, 15) and doc.moneda == "EUR"
    l = doc.lineas[0]
    assert l.precio == Decimal("50.00") and l.unidades == 2 and l.descuento_pct == 10
    assert l.precio_neto == Decimal("45.00")


def test_abono_v2_con_documento_origen():
    datos = {**COMPRA_V2, "id": "a1", "total": "-121.00", "from": {"id": "000000000000000000000001", "doc_type": "purchase"}}
    doc = nh.documento(datos, ABONO)
    assert doc.es_abono and doc.origen_id == "000000000000000000000001"


def test_timestamp_v1_de_medianoche_en_madrid_conserva_el_dia():
    doc = nh.documento({"id": "v1", "date": 1768431600, "total": 1}, COMPRA)
    assert doc.fecha == date(2026, 1, 15)
    docs, _ = nh.normalizar([{"id": "v1", "date": 1768431600}], [], [], zona_horaria="UTC")
    assert docs[0].fecha == date(2026, 1, 14)


def test_documento_v1_camelcase_y_timestamp():
    datos = {"id": "v1", "docNumber": "A/7", "contact": "c9", "contactName": "Otro Ficticio SL",
             "desc": "Texto", "date": 1768435200, "total": 50,
             "notes": [{"description": "nota uno"}],
             "products": [{"name": "Cosa", "price": 5, "units": 10}]}
    doc = nh.documento(datos, COMPRA)
    assert doc.numero == "A/7" and doc.proveedor_id == "c9" and doc.proveedor_nombre == "Otro Ficticio SL"
    assert doc.fecha == date(2026, 1, 15) and doc.notas == "nota uno"
    assert doc.lineas[0].unidades == 10


def test_contactos():
    prov = nh.contacto({"id": "c1", "name": "Proveedor Ejemplo SL", "code": "B00000001", "type": "supplier"})
    acreedor = nh.contacto({"id": "c2", "name": "Acreedor Ficticio", "vat_number": "ESB00000002", "type": "creditor"})
    cliente_y_prov = nh.contacto({"id": "c3", "name": "Mixto", "type": "client", "supplier_record": {"num": 400001}})
    cliente = nh.contacto({"id": "c4", "name": "Cliente", "type": "client", "supplier_record": {"num": None}})
    assert prov.es_proveedor and prov.nif == "B00000001"
    assert acreedor.es_proveedor and acreedor.nif == "ESB00000002"
    assert cliente_y_prov.es_proveedor
    assert not cliente.es_proveedor
