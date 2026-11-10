"""Rutas, configuración por empresa y lectura de la clave de la API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from .reglas import (
    CONCEPTOS_PRECIO_VARIABLE,
    PALABRAS_ABONO,
    PALABRAS_ABONO_SOLO_CABECERA,
    PALABRAS_PRESUPUESTO,
    Parametros,
)
from .texto import ZONA_HORARIA, zona_valida

VARIABLE_CLAVE = "HOLDED_API_KEY"
RAIZ_AUTOMATIZACION = Path(__file__).resolve().parents[1]     # .../02-revision-compras
RAIZ_REPO = Path(__file__).resolve().parents[3]               # .../automatizaciones-admin


def variable_clave_empresa(empresa: str) -> str:
    """Nombre de la variable con la clave de una empresa: HOLDED_API_KEY_<EMPRESA>."""
    return f"{VARIABLE_CLAVE}_" + re.sub(r"[^A-Z0-9]", "_", empresa.upper())


def instrucciones_clave(empresa: str, hay_generica: bool = False) -> str:
    variable = variable_clave_empresa(empresa)
    texto = f"""\
No se encuentra la clave de la API de Holded de la empresa «{empresa}» ({variable}).

Cada empresa tiene su propia clave, para no descargar los datos de una empresa
con el nombre de otra.

Cómo crearla (la crea una persona con acceso a Desarrolladores en el Holded de esa empresa):
  1. En Holded: menú de la cuenta > Configuración > Desarrolladores > Credenciales.
  2. "Agregar API Token" y marca SOLO LECTURA en Compras y en Contactos.
  3. "Crear Token" y copia el valor (solo se muestra una vez).

Cómo dársela a este programa (elige una opción):
  - Variable de entorno:  export {variable}=...
  - Archivo clientes/{empresa}/.env con la línea  {VARIABLE_CLAVE}=...
  - Archivo .env en la raíz del repositorio (copia .env.example a .env) con la línea
    {variable}=...
  Los .env y la carpeta clientes/{empresa}/ están en .gitignore: nunca se suben a GitHub.

Si ya descargaste los datos antes, puedes revisar sin clave con --cache."""
    if hay_generica:
        texto += f"""

Hay una clave genérica {VARIABLE_CLAVE}, pero no se usa sin pedirlo porque no se
sabe de qué empresa es. Si es la de «{empresa}», ejecuta con --clave-generica."""
    return texto


class ErrorConfiguracion(Exception):
    """Falta la configuración o es incorrecta. El mensaje explica cómo arreglarlo."""


# ---------------------------------------------------------------- clave API

@dataclass(frozen=True)
class Clave:
    """Clave de la API y de dónde se ha leído. ``repr`` nunca muestra el valor."""

    valor: str = field(repr=False)
    origen: str


def _leer_env(ruta: Path) -> dict[str, str]:
    """Lee un archivo .env sencillo (CLAVE=valor, comentarios con #) sin dependencias."""
    valores: dict[str, str] = {}
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return valores
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        if linea.startswith("export "):
            linea = linea[len("export "):].strip()
        nombre, _, valor = linea.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
            valor = valor[1:-1]
        else:
            valor = re.split(r"\s+#", valor, maxsplit=1)[0].strip()
        valores[nombre.strip()] = valor
    return valores


def _origenes_clave(empresa: str, entorno, raiz_repo: Path, generica: bool):
    """(descripción, función que lee el valor) en orden de prioridad."""
    variable = variable_clave_empresa(empresa)
    env_empresa = raiz_repo / "clientes" / empresa / ".env"
    env_repo = raiz_repo / ".env"
    origenes = [
        (f"variable de entorno {variable}", lambda: entorno.get(variable)),
        (f"clientes/{empresa}/.env ({variable})", lambda: _leer_env(env_empresa).get(variable)),
        (f"clientes/{empresa}/.env ({VARIABLE_CLAVE})", lambda: _leer_env(env_empresa).get(VARIABLE_CLAVE)),
        (f".env del repositorio ({variable})", lambda: _leer_env(env_repo).get(variable)),
    ]
    if generica:
        origenes += [
            (f"variable de entorno {VARIABLE_CLAVE} (genérica)", lambda: entorno.get(VARIABLE_CLAVE)),
            (f".env del repositorio ({VARIABLE_CLAVE}, genérica)", lambda: _leer_env(env_repo).get(VARIABLE_CLAVE)),
        ]
    return origenes


def cargar_clave(
    empresa: str,
    entorno: dict | None = None,
    raiz_repo: Path = RAIZ_REPO,
    generica: bool = False,
) -> Clave | None:
    """Devuelve la clave de la empresa (con su origen) o None.

    Prioridad: variable HOLDED_API_KEY_<EMPRESA>, clientes/<empresa>/.env y
    HOLDED_API_KEY_<EMPRESA> en el .env del repositorio. La HOLDED_API_KEY
    genérica solo se usa si ``generica`` es True (opción --clave-generica).
    No se lee el .env del directorio actual: ejecutar desde otra carpeta no
    puede cambiar la clave sin avisar. La clave no se escribe en ningún sitio
    ni se copia a os.environ.
    """
    validar_empresa(empresa)
    entorno = os.environ if entorno is None else entorno
    for origen, leer in _origenes_clave(empresa, entorno, raiz_repo, generica):
        valor = (leer() or "").strip()
        if valor:
            return Clave(valor, origen)
    return None


def hay_clave_generica(entorno: dict | None = None, raiz_repo: Path = RAIZ_REPO) -> bool:
    entorno = os.environ if entorno is None else entorno
    return bool(
        (entorno.get(VARIABLE_CLAVE) or "").strip()
        or (_leer_env(raiz_repo / ".env").get(VARIABLE_CLAVE) or "").strip()
    )


# ------------------------------------------------------------ configuración

@dataclass(frozen=True)
class Configuracion:
    empresa: str
    nombre_empresa: str
    ruta: Path
    parametros: Parametros
    fecha_desde: date | None
    version_api: str = "v2"
    zona_horaria: str = ZONA_HORARIA


def ruta_config(empresa: str, raiz_repo: Path = RAIZ_REPO) -> Path:
    return raiz_repo / "clientes" / empresa / "config.yaml"


def _lista(valor, defecto: tuple[str, ...], campo: str) -> tuple[str, ...]:
    if valor is None:
        return defecto
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list) or not all(isinstance(v, (str, int)) for v in valor):
        raise ErrorConfiguracion(f"revision_compras.{campo} debe ser una lista de palabras.")
    return tuple(str(v) for v in valor if str(v).strip())


def _fecha(valor, campo: str) -> date | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        raise ErrorConfiguracion(f"{campo} debe tener el formato AAAA-MM-DD (por ejemplo 2026-01-01).") from None


def validar_empresa(empresa: str) -> str:
    if not empresa or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]*", empresa) or empresa == "_plantilla":
        raise ErrorConfiguracion(
            "El nombre de empresa solo puede llevar letras, números, guiones y guiones bajos "
            "(es el nombre de la carpeta clientes/<empresa>/)."
        )
    return empresa


def cargar_configuracion(empresa: str, ruta: Path | None = None, raiz_repo: Path = RAIZ_REPO) -> Configuracion:
    validar_empresa(empresa)
    ruta = Path(ruta) if ruta else ruta_config(empresa, raiz_repo)
    if not ruta.is_file():
        raise ErrorConfiguracion(
            f"No existe la configuración de la empresa «{empresa}»: {ruta}\n\n"
            "Créala así:\n"
            f"  1. Copia la carpeta clientes/_plantilla/ como clientes/{empresa}/ "
            "(esa carpeta no se sube a GitHub).\n"
            f"  2. Renombra config.example.yaml a config.yaml.\n"
            "  3. Rellena empresa.nif y la sección revision_compras (nif_propio, fecha_desde...)."
        )
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ErrorConfiguracion(f"El archivo {ruta} no es un YAML válido: {e}") from None
    if not isinstance(datos, dict):
        raise ErrorConfiguracion(f"El archivo {ruta} debe contener un diccionario YAML.")

    empresa_datos = datos.get("empresa") or {}
    seccion = datos.get("revision_compras") or {}
    if not isinstance(seccion, dict):
        raise ErrorConfiguracion("La sección revision_compras debe ser un diccionario.")

    nif_propio = str(seccion.get("nif_propio") or empresa_datos.get("nif") or "").strip()
    umbral_bruto = seccion.get("umbral_subida_precio", 5)
    try:
        umbral = Decimal(str(umbral_bruto))
    except InvalidOperation:
        raise ErrorConfiguracion("revision_compras.umbral_subida_precio debe ser un número (por ejemplo 5).") from None
    if umbral < 0:
        raise ErrorConfiguracion("revision_compras.umbral_subida_precio no puede ser negativo.")

    version = str(seccion.get("api_holded") or "v2").strip().lower()
    if version not in ("v1", "v2"):
        raise ErrorConfiguracion('revision_compras.api_holded debe ser "v2" (recomendado) o "v1".')

    zona_horaria = str(seccion.get("zona_horaria") or ZONA_HORARIA).strip()
    if not zona_valida(zona_horaria):
        raise ErrorConfiguracion(
            "revision_compras.zona_horaria debe ser una zona IANA (por ejemplo Europe/Madrid o Atlantic/Canary)."
        )

    parametros = Parametros(
        nif_propio=nif_propio,
        umbral_subida_precio=umbral,
        palabras_abono=_lista(seccion.get("palabras_abono"), PALABRAS_ABONO, "palabras_abono"),
        palabras_abono_solo_cabecera=_lista(
            seccion.get("palabras_abono_solo_cabecera"), PALABRAS_ABONO_SOLO_CABECERA, "palabras_abono_solo_cabecera"
        ),
        palabras_presupuesto=_lista(seccion.get("palabras_presupuesto"), PALABRAS_PRESUPUESTO, "palabras_presupuesto"),
        conceptos_precio_variable=_lista(
            seccion.get("conceptos_precio_variable"), CONCEPTOS_PRECIO_VARIABLE, "conceptos_precio_variable"
        ),
    )
    return Configuracion(
        empresa=empresa,
        nombre_empresa=str(empresa_datos.get("nombre") or empresa),
        ruta=ruta,
        parametros=parametros,
        fecha_desde=_fecha(seccion.get("fecha_desde"), "revision_compras.fecha_desde"),
        version_api=version,
        zona_horaria=zona_horaria,
    )
