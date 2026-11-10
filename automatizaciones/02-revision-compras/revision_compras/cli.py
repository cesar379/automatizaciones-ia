"""Línea de órdenes: python -m revision_compras --empresa <empresa> [--desde AAAA-MM-DD] [--cache | --exportacion ARCHIVO] [--clave-generica]."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from openpyxl.utils.exceptions import IllegalCharacterError

from . import normalizar_exportacion, normalizar_holded
from .configuracion import (
    RAIZ_AUTOMATIZACION,
    RAIZ_REPO,
    VARIABLE_CLAVE,
    Configuracion,
    ErrorConfiguracion,
    cargar_clave,
    cargar_configuracion,
    hay_clave_generica,
    instrucciones_clave,
)
from .holded import ClienteHolded, ErrorHolded
from .informe import escribir_excel, escribir_markdown, importe_total
from .modelo import ALTA, BAJA, MEDIA
from .reglas import revisar
from .texto import euros

ARCHIVOS = {"compras": "compras.json", "abonos": "abonos.json", "contactos": "contactos.json"}
META = "descarga.json"

SALIDA_OK = 0
SALIDA_ERROR_API = 1
SALIDA_ERROR_CONFIG = 2


class _Analizador(argparse.ArgumentParser):
    def error(self, message):  # mensajes de uso en español
        self.print_usage(sys.stderr)
        self.exit(SALIDA_ERROR_CONFIG, f"Error en los argumentos: {message}\n")


def _argumentos(argv):
    p = _Analizador(
        prog="python -m revision_compras",
        description="Revisa las compras de Holded (solo lectura) y genera un informe de avisos.",
        add_help=False,
    )
    p.add_argument("-h", "--help", action="help", help="Muestra esta ayuda y termina.")
    p.add_argument("--empresa", required=True, help="Nombre de la carpeta clientes/<empresa>/ (p. ej. ejemplo).")
    p.add_argument("--desde", help="Revisar compras desde esta fecha (AAAA-MM-DD). Por defecto, la de la configuración.")
    p.add_argument("--cache", action="store_true", help="Reutilizar lo ya descargado en datos/<empresa>/ sin llamar a la API.")
    p.add_argument("--config", help="Ruta alternativa al config.yaml de la empresa.")
    p.add_argument(
        "--exportacion", metavar="ARCHIVO",
        help="Usar el Excel de Holded «Compras > Acciones > Exportar líneas» en lugar de la API (no necesita clave).",
    )
    p.add_argument(
        "--clave-generica", action="store_true",
        help=f"Usar la clave genérica {VARIABLE_CLAVE} si la empresa no tiene la suya "
             f"({VARIABLE_CLAVE}_<EMPRESA> o clientes/<empresa>/.env).",
    )
    return p.parse_args(argv)


def _fecha_desde(texto: str | None, config: Configuracion, hoy: date) -> date:
    if texto:
        try:
            return date.fromisoformat(texto)
        except ValueError:
            raise ErrorConfiguracion("--desde debe tener el formato AAAA-MM-DD (por ejemplo 2026-01-01).") from None
    if config.fecha_desde:
        return config.fecha_desde
    return date(hoy.year - 1, 1, 1)


def _guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    temporal.replace(ruta)


def descargar(cliente: ClienteHolded, carpeta: Path, desde: date, avisar: Callable[[str], None]) -> dict:
    desde_txt = desde.isoformat()
    avisar("Descargando compras de Holded (solo lectura)...")
    compras = cliente.compras(desde_txt)
    avisar(f"  {len(compras)} compras. Descargando compras rectificativas (abonos)...")
    abonos = cliente.abonos(desde_txt)
    avisar(f"  {len(abonos)} abonos. Descargando contactos...")
    contactos = cliente.contactos()
    avisar(f"  {len(contactos)} contactos. Peticiones a la API: {cliente.peticiones}.")
    datos = {"compras": compras, "abonos": abonos, "contactos": contactos}
    for clave, nombre in ARCHIVOS.items():
        _guardar_json(carpeta / nombre, datos[clave])
    _guardar_json(carpeta / META, {
        "descargado": datetime.now().isoformat(timespec="seconds"),
        "desde": desde_txt,
        "api": cliente.version,
        "compras": len(compras),
        "abonos": len(abonos),
        "contactos": len(contactos),
    })
    return datos


def leer_cache(carpeta: Path, desde: date, avisar: Callable[[str], None]) -> dict:
    faltan = [n for n in ARCHIVOS.values() if not (carpeta / n).is_file()]
    if faltan:
        raise ErrorConfiguracion(
            f"No hay datos descargados en {carpeta} (faltan: {', '.join(faltan)}).\n"
            "Ejecuta primero sin --cache para descargarlos de Holded."
        )
    datos = {}
    for clave, nombre in ARCHIVOS.items():
        try:
            datos[clave] = json.loads((carpeta / nombre).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ErrorConfiguracion(f"El archivo {carpeta / nombre} está dañado. Vuelve a descargar sin --cache.") from None
        if not isinstance(datos[clave], list):
            raise ErrorConfiguracion(f"El archivo {carpeta / nombre} no tiene el formato esperado (lista).")
    try:
        meta = json.loads((carpeta / META).read_text(encoding="utf-8"))
        desde_cache = date.fromisoformat(meta.get("desde"))
        if desde < desde_cache:
            avisar(
                f"Aviso: los datos guardados empiezan el {desde_cache.strftime('%d/%m/%Y')}; "
                f"no incluyen compras anteriores. Descarga de nuevo sin --cache para ampliar el periodo."
            )
        avisar(f"Usando datos descargados el {meta.get('descargado', '?')} (sin llamar a la API).")
    except (OSError, ValueError, TypeError, AttributeError):
        avisar("Usando datos descargados previamente (sin llamar a la API).")
    return datos


def notas_del_informe(documentos, desde_exportacion: bool = False) -> list[str]:
    """Limitaciones de los datos que conviene explicar en el informe."""
    notas = list(normalizar_exportacion.NOTAS_EXPORTACION) if desde_exportacion else []
    compras = [d for d in documentos if not d.es_abono]
    if compras and not desde_exportacion and not any(d.notas for d in compras):
        notas.append(
            "Los datos no traen las notas de las compras (el listado de la API v2 de Holded no las incluye): "
            "la regla de abonos pendientes solo ha buscado en la descripción y en las líneas."
        )
    monedas = sorted({(d.moneda or "EUR").upper() for d in documentos} - {"EUR"})
    if monedas:
        notas.append(
            f"Hay documentos en {', '.join(monedas)}: se comparan solo con documentos de la misma moneda "
            "y su importe no se suma al importe en juego en euros."
        )
    return notas


def main(
    argv=None,
    *,
    raiz_automatizacion: Path = RAIZ_AUTOMATIZACION,
    raiz_repo: Path = RAIZ_REPO,
    entorno: dict | None = None,
    fabrica_cliente: Callable[..., ClienteHolded] = ClienteHolded,
    hoy: date | None = None,
    salida=None,
) -> int:
    salida = salida or sys.stdout
    hoy = hoy or date.today()

    def avisar(mensaje: str) -> None:
        print(mensaje, file=salida, flush=True)

    def error(mensaje: str) -> None:
        print(f"ERROR: {mensaje}", file=sys.stderr, flush=True)

    args = _argumentos(argv)
    try:
        config = cargar_configuracion(args.empresa, Path(args.config) if args.config else None, raiz_repo)
        desde = _fecha_desde(args.desde, config, hoy)
        carpeta_datos = raiz_automatizacion / "datos" / config.empresa
        datos = None
        if args.exportacion:
            if args.cache:
                raise ErrorConfiguracion("Usa --cache o --exportacion, no las dos a la vez.")
            avisar(f"Leyendo la exportación de Holded: {Path(args.exportacion).name} (sin llamar a la API).")
            documentos, contactos = normalizar_exportacion.leer_exportacion(Path(args.exportacion))
        elif args.cache:
            datos = leer_cache(carpeta_datos, desde, avisar)
        else:
            clave = cargar_clave(config.empresa, entorno, raiz_repo, generica=args.clave_generica)
            if not clave:
                error(instrucciones_clave(config.empresa, hay_clave_generica(entorno, raiz_repo)))
                return SALIDA_ERROR_CONFIG
            avisar(f"Clave de Holded leída de: {clave.origen}.")
            cliente = fabrica_cliente(clave.valor, version=config.version_api, registrar=avisar,
                                      zona_horaria=config.zona_horaria)
            del clave
            datos = descargar(cliente, carpeta_datos, desde, avisar)
    except ErrorConfiguracion as e:
        error(str(e))
        return SALIDA_ERROR_CONFIG
    except normalizar_exportacion.ErrorExportacion as e:
        error(str(e))
        return SALIDA_ERROR_CONFIG
    except ErrorHolded as e:
        error(str(e))
        return SALIDA_ERROR_API

    if datos is not None:
        documentos, contactos = normalizar_holded.normalizar(
            datos["compras"], datos["abonos"], datos["contactos"], config.zona_horaria
        )
    documentos = [d for d in documentos if d.fecha is None or d.fecha >= desde]
    avisos = revisar(documentos, contactos, config.parametros)
    notas = notas_del_informe(documentos, desde_exportacion=bool(args.exportacion))

    carpeta = raiz_automatizacion / "resultados" / config.empresa
    nombre = f"revision_compras_{hoy.isoformat()}"
    try:
        excel = escribir_excel(avisos, carpeta / f"{nombre}.xlsx", config.nombre_empresa, hoy, desde,
                               len(documentos), len(contactos), notas)
        resumen = escribir_markdown(avisos, carpeta / f"{nombre}.md", config.nombre_empresa, hoy, desde,
                                    len(documentos), len(contactos), excel.name, notas=notas)
    except (OSError, IllegalCharacterError) as e:  # p. ej. el Excel anterior está abierto
        error(
            f"No se pudo escribir el informe en {carpeta} ({type(e).__name__}). "
            "Cierra el archivo si está abierto y vuelve a ejecutar con --cache (los datos ya están descargados)."
        )
        return SALIDA_ERROR_CONFIG

    n = {p: sum(1 for a in avisos if a.prioridad == p) for p in (ALTA, MEDIA, BAJA)}
    avisar("")
    avisar(f"Revisadas {len(documentos)} compras y abonos desde el {desde.strftime('%d/%m/%Y')}.")
    avisar(f"Avisos: {len(avisos)} (alta {n[ALTA]}, media {n[MEDIA]}, baja {n[BAJA]}); "
           f"importe en juego {euros(importe_total(avisos))}.")
    avisar(f"Informe Excel: {excel}")
    avisar(f"Resumen:       {resumen}")
    avisar("No se ha modificado nada en Holded.")
    return SALIDA_OK
