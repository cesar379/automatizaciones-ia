"""Lectura de la exportación «Exportar líneas» de Holded, con un Excel 100 % ficticio."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from revision_compras import cli
from revision_compras.modelo import ABONO, COMPRA
from revision_compras.normalizar_exportacion import ErrorExportacion, leer_exportacion
from revision_compras.reglas import revisar

CABECERA = ["Invoice num", "Internal num", "Date", "Due date", "Description", "Draft", "Contact", "Contact ID",
            "Postal code", "City", "Country", "SKU", "Item", "Tags", "Project", "Account", "Units", "Subtotal",
            "Tax", "Total tax", "Total"]


def fila(num, fecha, proveedor, nif, item, unidades, subtotal, iva_pct=21, desc="", draft="No", sku=None):
    iva = round(subtotal * iva_pct / 100, 2)
    return [num, None, datetime.fromisoformat(fecha + " 19:10:07"), None, desc, draft, proveedor, nif,
            None, None, "España", sku, item, None, "-", "Compras de mercaderías", unidades, subtotal, iva, iva,
            round(subtotal + iva, 2)]


def escribir(ruta: Path, filas) -> Path:
    libro = Workbook()
    hoja = libro.active
    hoja.append(["Empresa Ficticia SL"])
    hoja.append(["Purchases Export items"])
    hoja.append([])
    hoja.append(CABECERA)
    for f in filas:
        hoja.append(f)
    hoja.append([])
    hoja.append(["Report powered automatically by Holded - 10/11/2026 20:10"])
    libro.save(ruta)
    return ruta


@pytest.fixture
def exportacion(tmp_path):
    return escribir(tmp_path / "lineas.xlsx", [
        fila("F-1", "2026-03-01", "Proveedor Ejemplo SL", "B00000001", "Producto A", 10, 100, sku="PA"),
        fila("F-1", "2026-03-01", "Proveedor Ejemplo SL", "B00000001", "Portes", 1, 20),
        fila("F-2", "2026-04-01", "Proveedor Ejemplo SL", "B00000001", "Producto A", 10, 120, sku="PA"),
        fila("R-1", "2026-04-05", "Proveedor Ejemplo SL", "B00000001", "Devolución", -1, -50),
        fila("7", "2026-04-07", "Otro Proveedor SL", "B00000002", "Servicio", 1, 4000),
        fila("8", "2026-04-07", "Otro Proveedor SL", "B00000002", "Servicio", 1, 4000),
        fila("A-9", "2026-05-01", "Proveedor Doble SL", "B00000099", "Producto B", 1, 60),
        fila("A-10", "2026-05-02", "Proveedor Doble, S.L.", "B00000003", "Producto B", 1, 60),
        fila("X-1", "2026-05-03", "Proveedor Ejemplo SL", "B00000001", "Producto C", 1, 10, draft="Sí"),
    ])


def test_agrupa_lineas_por_documento_y_detecta_abonos(exportacion):
    documentos, contactos = leer_exportacion(exportacion)
    por_numero = {d.numero: d for d in documentos}
    assert "X-1" not in por_numero  # los borradores se ignoran
    assert all(d.proveedor_nombre for d in documentos)  # el pie del informe no es un documento
    assert len(documentos) == 7
    f1 = por_numero["F-1"]
    assert f1.tipo == COMPRA and len(f1.lineas) == 2 and f1.fecha == date(2026, 3, 1)
    assert f1.subtotal == Decimal("120") and f1.total == Decimal("145.2")
    assert f1.lineas[0].precio == Decimal("10") and f1.lineas[0].sku == "PA"
    assert f1.lineas[0].impuesto_pct == Decimal("21.00")
    assert por_numero["R-1"].tipo == ABONO
    assert por_numero["7"].numero == "7"  # números guardados como entero en el Excel
    assert {c.nif for c in contactos} == {"B00000001", "B00000002", "B00000099", "B00000003"}
    assert all(c.es_proveedor for c in contactos)


def test_reglas_sobre_la_exportacion(exportacion):
    documentos, contactos = leer_exportacion(exportacion)
    from revision_compras.configuracion import Parametros
    avisos = revisar(documentos, contactos, Parametros(nif_propio="B00000099"))
    tipos = {(a.tipo, a.proveedor) for a in avisos}
    textos = " ".join(f"{a.tipo} {a.proveedor} {a.documentos} {a.detalle}" for a in avisos).lower()
    assert any("duplic" in t and "Otro Proveedor" in p for t, p in tipos), avisos
    assert any("precio" in t.lower() for t, _ in tipos), avisos
    assert "b00000099" in textos.replace("-", "")  # ficha con el NIF propio
    assert any("Doble" in p for _, p in tipos)    # dos fichas con el mismo nombre


def test_archivo_que_no_es_exportacion(tmp_path):
    ruta = tmp_path / "otro.xlsx"
    libro = Workbook()
    libro.active.append(["a", "b"])
    libro.save(ruta)
    with pytest.raises(ErrorExportacion):
        leer_exportacion(ruta)
    with pytest.raises(ErrorExportacion):
        leer_exportacion(tmp_path / "no_existe.xlsx")


def test_cli_con_exportacion_sin_clave(tmp_path, exportacion, capsys):
    repo = tmp_path / "repo"
    (repo / "clientes" / "ficticia").mkdir(parents=True)
    (repo / "clientes" / "ficticia" / "config.yaml").write_text(
        'empresa:\n  nombre: "Empresa Ficticia, S.L."\n  nif: "B00000099"\n'
        "revision_compras:\n  nif_propio: \"B00000099\"\n  fecha_desde: 2026-01-01\n",
        encoding="utf-8",
    )
    salida = tmp_path / "salida"
    codigo = cli.main(["--empresa", "ficticia", "--exportacion", str(exportacion)],
                      raiz_automatizacion=salida, raiz_repo=repo, entorno={}, hoy=date(2026, 11, 10))
    assert codigo == cli.SALIDA_OK
    resultados = list((salida / "resultados" / "ficticia").iterdir())
    assert {r.suffix for r in resultados} == {".xlsx", ".md"}
    md = next(r for r in resultados if r.suffix == ".md").read_text(encoding="utf-8")
    assert "exportación de líneas" in md
    assert not (salida / "datos").exists()  # no descarga nada


def test_cli_rechaza_cache_y_exportacion_juntas(tmp_path, exportacion):
    repo = tmp_path / "repo"
    (repo / "clientes" / "ficticia").mkdir(parents=True)
    (repo / "clientes" / "ficticia" / "config.yaml").write_text("revision_compras: {}\n", encoding="utf-8")
    codigo = cli.main(["--empresa", "ficticia", "--exportacion", str(exportacion), "--cache"],
                      raiz_automatizacion=tmp_path, raiz_repo=repo, entorno={}, hoy=date(2026, 11, 10))
    assert codigo == cli.SALIDA_ERROR_CONFIG
