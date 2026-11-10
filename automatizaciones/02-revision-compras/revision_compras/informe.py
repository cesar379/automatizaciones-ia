"""Informe de la revisión: Excel (Resumen + Avisos) y resumen en Markdown."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .modelo import ALTA, BAJA, CERO, MEDIA, Aviso
from .reglas import TIPOS
from .texto import euros

FUENTE = "Arial"
FORMATO_FECHA = "dd/mm/yyyy"
FORMATO_EUROS = '#,##0.00 "€";-#,##0.00 "€"'
PRIORIDADES = (ALTA, MEDIA, BAJA)
COLORES = {ALTA: "F4CCCC", MEDIA: "FCE5CD", BAJA: "D9EAD3"}
CABECERA_FONDO = "1F3864"

COLUMNAS = (
    ("Prioridad", 10),
    ("Tipo", 28),
    ("Proveedor", 32),
    ("Documento(s)", 32),
    ("Fecha", 12),
    ("Importe en juego (€)", 18),
    ("Detalle", 70),
    ("Acción sugerida", 55),
)


def _f(negrita: bool = False, color: str | None = None, tam: int = 10) -> Font:
    return Font(name=FUENTE, bold=negrita, color=color, size=tam)


def limpiar_texto(texto: str) -> str:
    """Quita los caracteres de control que Excel no admite (salto de página, tabulador vertical...)."""
    return ILLEGAL_CHARACTERS_RE.sub("", texto)


def _dato(hoja, fila: int, columna: int, valor):
    """Escribe un dato que puede venir del ERP: nunca como fórmula.

    openpyxl convierte en fórmula cualquier texto que empiece por "=". Un nombre de
    proveedor o un número de factura así ("=HYPERLINK(...)") quedaría activo en el
    informe; aquí se guarda siempre como texto.
    """
    if isinstance(valor, str):
        valor = limpiar_texto(valor)
    celda = hoja.cell(row=fila, column=columna, value=valor)
    if isinstance(valor, str) and celda.data_type == "f":
        celda.data_type = "s"
    return celda


def _cabecera(celda) -> None:
    celda.font = _f(True, "FFFFFF")
    celda.fill = PatternFill("solid", fgColor=CABECERA_FONDO)
    celda.alignment = Alignment(vertical="center", wrap_text=True)


def escribir_excel(
    avisos: Sequence[Aviso],
    ruta: Path,
    empresa: str,
    fecha_informe: date,
    desde: date | None,
    n_documentos: int,
    n_contactos: int,
    notas: Sequence[str] = (),
) -> Path:
    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen"
    hoja = libro.create_sheet("Avisos")

    # ---- Avisos
    for col, (titulo, ancho) in enumerate(COLUMNAS, start=1):
        _cabecera(hoja.cell(row=1, column=col, value=titulo))
        hoja.column_dimensions[get_column_letter(col)].width = ancho
    borde = Border(bottom=Side(style="hair", color="BFBFBF"))
    for fila, aviso in enumerate(avisos, start=2):
        valores = (
            aviso.prioridad.capitalize(),
            aviso.tipo,
            aviso.proveedor,
            aviso.documentos,
            aviso.fecha,
            float(aviso.importe),
            aviso.detalle,
            aviso.accion,
        )
        for col, valor in enumerate(valores, start=1):
            celda = _dato(hoja, fila, col, valor)
            celda.font = _f()
            celda.alignment = Alignment(vertical="top", wrap_text=col in (3, 4, 7, 8))
            celda.border = borde
        prioridad = hoja.cell(row=fila, column=1)
        prioridad.fill = PatternFill("solid", fgColor=COLORES.get(aviso.prioridad, "FFFFFF"))
        prioridad.font = _f(True)
        hoja.cell(row=fila, column=5).number_format = FORMATO_FECHA
        hoja.cell(row=fila, column=6).number_format = FORMATO_EUROS
    ultima = max(2, len(avisos) + 1)
    hoja.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{ultima}"
    hoja.freeze_panes = "A2"

    # ---- Resumen (fórmulas compatibles con Excel 2007: COUNTIF, SUMIF, COUNTIFS)
    rango_prioridad = f"Avisos!$A$2:$A${ultima}"
    rango_tipo = f"Avisos!$B$2:$B${ultima}"
    rango_importe = f"Avisos!$F$2:$F${ultima}"

    resumen.column_dimensions["A"].width = 34
    for letra in "BCDEF":
        resumen.column_dimensions[letra].width = 16

    resumen["A1"] = "Revisión de compras"
    resumen["A1"].font = _f(True, tam=14)
    info = (
        ("Empresa", empresa),
        ("Fecha del informe", fecha_informe),
        ("Compras desde", desde),
        ("Documentos revisados", n_documentos),
        ("Contactos revisados", n_contactos),
    )
    for i, (etiqueta, valor) in enumerate(info, start=3):
        resumen.cell(row=i, column=1, value=etiqueta).font = _f(True)
        celda = _dato(resumen, i, 2, valor if valor is not None else "todas")
        celda.font = _f()
        celda.alignment = Alignment(horizontal="left")
        if isinstance(valor, date):
            celda.number_format = FORMATO_FECHA

    fila = 10
    titulos = ("Tipo de aviso", "Avisos", "Alta", "Media", "Baja", "Importe en juego (€)")
    for col, titulo in enumerate(titulos, start=1):
        _cabecera(resumen.cell(row=fila, column=col, value=titulo))
    primera = fila + 1
    for i, tipo in enumerate(TIPOS):
        r = primera + i
        resumen.cell(row=r, column=1, value=tipo)
        resumen.cell(row=r, column=2, value=f"=COUNTIF({rango_tipo},$A{r})")
        for col, prioridad in zip((3, 4, 5), PRIORIDADES):
            resumen.cell(
                row=r, column=col,
                value=f'=COUNTIFS({rango_tipo},$A{r},{rango_prioridad},"{prioridad.capitalize()}")',
            )
        resumen.cell(row=r, column=6, value=f"=SUMIF({rango_tipo},$A{r},{rango_importe})")
    total = primera + len(TIPOS)
    resumen.cell(row=total, column=1, value="Total")
    for col in range(2, 7):
        letra = get_column_letter(col)
        resumen.cell(row=total, column=col, value=f"=SUM({letra}{primera}:{letra}{total - 1})")
    for r in range(primera, total + 1):
        for col in range(1, 7):
            celda = resumen.cell(row=r, column=col)
            celda.font = _f(r == total)
            if col == 6:
                celda.number_format = FORMATO_EUROS

    fila = total + 2
    for col, titulo in enumerate(("Prioridad", "Avisos", "Importe en juego (€)"), start=1):
        _cabecera(resumen.cell(row=fila, column=col, value=titulo))
    for i, prioridad in enumerate(PRIORIDADES, start=1):
        r = fila + i
        nombre = prioridad.capitalize()
        c = resumen.cell(row=r, column=1, value=nombre)
        c.font = _f(True)
        c.fill = PatternFill("solid", fgColor=COLORES[prioridad])
        resumen.cell(row=r, column=2, value=f"=COUNTIF({rango_prioridad},$A{r})").font = _f()
        celda = resumen.cell(row=r, column=3, value=f"=SUMIF({rango_prioridad},$A{r},{rango_importe})")
        celda.font = _f()
        celda.number_format = FORMATO_EUROS

    nota = fila + len(PRIORIDADES) + 2
    resumen.cell(
        row=nota, column=1,
        value="El importe en juego es orientativo y puede contar dos veces un mismo documento si tiene varios avisos.",
    ).font = _f(color="595959", tam=9)
    resumen.cell(
        row=nota + 1, column=1,
        value="Esta revisión solo lee el ERP: no ha modificado ningún dato.",
    ).font = _f(color="595959", tam=9)
    for i, texto in enumerate(notas, start=2):
        _dato(resumen, nota + i, 1, texto).font = _f(color="595959", tam=9)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)
    return ruta


def escribir_markdown(
    avisos: Sequence[Aviso],
    ruta: Path,
    empresa: str,
    fecha_informe: date,
    desde: date | None,
    n_documentos: int,
    n_contactos: int,
    nombre_excel: str,
    maximo_detalle: int = 15,
    notas: Sequence[str] = (),
) -> Path:
    por_tipo: dict[str, list[Aviso]] = defaultdict(list)
    for a in avisos:
        por_tipo[a.tipo].append(a)
    prioridades = Counter(a.prioridad for a in avisos)

    lineas = [
        f"# Revisión de compras · {empresa}",
        "",
        f"- Fecha del informe: {fecha_informe.strftime('%d/%m/%Y')}",
        f"- Compras desde: {desde.strftime('%d/%m/%Y') if desde else 'todas'}",
        f"- Documentos revisados: {n_documentos} · Contactos revisados: {n_contactos}",
        f"- Avisos: {len(avisos)} (alta {prioridades[ALTA]}, media {prioridades[MEDIA]}, baja {prioridades[BAJA]})",
        f"- Detalle completo: `{nombre_excel}`",
        "",
        "## Avisos por tipo",
        "",
        "| Tipo | Avisos | Alta | Media | Baja | Importe en juego |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tipo in TIPOS:
        lista = por_tipo.get(tipo, [])
        c = Counter(a.prioridad for a in lista)
        importe = sum((a.importe for a in lista), CERO)
        lineas.append(f"| {tipo} | {len(lista)} | {c[ALTA]} | {c[MEDIA]} | {c[BAJA]} | {euros(importe)} |")

    if avisos:
        lineas += ["", f"## Primeros avisos (máximo {maximo_detalle}, por prioridad e importe)", ""]
        for a in list(avisos)[:maximo_detalle]:
            fecha = a.fecha.strftime("%d/%m/%Y") if a.fecha else "—"
            lineas.append(
                f"- **{a.prioridad.capitalize()} · {a.tipo}** · {_md(a.proveedor) or '—'} · "
                f"{_md(a.documentos)} · {fecha} · {euros(a.importe)}  \n"
                f"  {_md(a.detalle)}  \n  _Acción:_ {_md(a.accion)}"
            )
    else:
        lineas += ["", "No hay avisos: no se ha encontrado nada que revisar con las reglas actuales."]
    if notas:
        lineas += ["", "## Notas", ""] + [f"- {_md(n)}" for n in notas]
    lineas += ["", "_Revisión de solo lectura: no se ha modificado ningún dato del ERP._", ""]

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


def _md(texto: str) -> str:
    return limpiar_texto(texto or "").replace("|", "/").replace("\n", " ")


def importe_total(avisos: Sequence[Aviso]) -> Decimal:
    return sum((a.importe for a in avisos), CERO)
