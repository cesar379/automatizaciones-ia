"""Funciones puras de normalización de textos, números e importes."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .modelo import CERO

ZONA_HORARIA = "Europe/Madrid"
MONEDA_BASE = "EUR"
LONGITUD_MINIMA_NIF = 8
DIGITOS_MINIMOS_SIN_SEPARADOR = 5

_FORMAS_JURIDICAS = {
    "sl", "sa", "slu", "sau", "sll", "slne", "slp", "scp", "sc", "cb",
    "scoop", "coop", "sccl", "srl", "ltd", "llc", "gmbh", "inc",
}
_FRASES_JURIDICAS = (
    "sociedad limitada unipersonal",
    "sociedad limitada",
    "sociedad anonima",
    "sociedad cooperativa",
    "comunidad de bienes",
)


def sin_acentos(texto: str) -> str:
    """Quita tildes y diéresis, conserva la ñ como n."""
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def texto_busqueda(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios simples."""
    return re.sub(r"\s+", " ", sin_acentos(texto).lower()).strip()


def contiene_palabra(texto: str, palabras) -> str | None:
    """Devuelve la primera palabra (o frase) encontrada al inicio de una palabra del texto.

    La comparación no distingue mayúsculas ni acentos. "devolucion" encuentra
    "devoluciones" y "Devolución", pero "error" no encuentra "terror".
    """
    normal = texto_busqueda(texto)
    if not normal:
        return None
    for palabra in palabras:
        clave = texto_busqueda(str(palabra))
        if clave and re.search(r"(?<!\w)" + re.escape(clave), normal):
            return str(palabra)
    return None


def empieza_por_palabra(texto: str, palabras) -> str | None:
    """Como contiene_palabra(), pero solo si el texto EMPIEZA por la palabra o frase.

    "Presupuesto reforma" empieza por "presupuesto"; "Reforma según presupuesto nº 45" no.
    """
    normal = re.sub(r"^[^\w]+", "", texto_busqueda(texto))
    if not normal:
        return None
    for palabra in palabras:
        clave = texto_busqueda(str(palabra))
        if clave and re.match(re.escape(clave), normal):
            return str(palabra)
    return None


def _partes_numero(numero: str) -> list[str]:
    """Bloques de letras y de cifras, en mayúsculas y sin separadores ni acentos."""
    return re.findall(r"[A-Z]+|\d+", sin_acentos(str(numero or "")).upper())


def normalizar_numero_documento(numero: str) -> str:
    """Número de documento comparable.

    En mayúsculas, sin espacios, guiones, barras ni puntos y sin ceros a la
    izquierda en cada bloque de cifras: "F-2026/0007" -> "F2026|7". Entre dos
    bloques de cifras seguidos se deja la marca "|" para que "01/12" ("1|12")
    y "11/02" ("11|2") no coincidan.
    """
    resultado = ""
    anterior_numerico = False
    for parte in _partes_numero(numero):
        numerico = parte.isdigit()
        if numerico:
            parte = parte.lstrip("0") or "0"
            if anterior_numerico:
                resultado += "|"
        resultado += parte
        anterior_numerico = numerico
    return resultado


def es_numero_generico(numero: str) -> bool:
    """True si el número no identifica el documento: vacío, "S/N", "Ticket", "0", "000"...

    Un número sin ninguna cifra distinta de cero no sirve para detectar duplicados.
    """
    return not re.search(r"[1-9]", sin_acentos(str(numero or "")))


def mismo_numero_documento(a: str, b: str) -> bool:
    """Compara dos números de documento ya escritos por personas distintas.

    Coinciden si su forma normalizada es igual ("F-0001" = "f 1") o si uno se
    ha escrito con separador y el otro sin él, con las mismas letras y las
    mismas cifras ("F2026-0001" = "F20260001"). Los números genéricos ("S/N",
    "Ticket", "0") nunca coinciden.
    """
    if es_numero_generico(a) or es_numero_generico(b):
        return False
    if normalizar_numero_documento(a) == normalizar_numero_documento(b):
        return True
    partes_a, partes_b = _partes_numero(a), _partes_numero(b)
    cifras_a = [p for p in partes_a if p.isdigit()]
    cifras_b = [p for p in partes_b if p.isdigit()]
    if len(cifras_a) == len(cifras_b) or min(len(cifras_a), len(cifras_b)) != 1:
        return False
    letras_a = "".join(p for p in partes_a if not p.isdigit())
    letras_b = "".join(p for p in partes_b if not p.isdigit())
    juntas_a, juntas_b = "".join(cifras_a), "".join(cifras_b)
    return letras_a == letras_b and juntas_a == juntas_b and len(juntas_a) >= DIGITOS_MINIMOS_SIN_SEPARADOR


def normalizar_nif(nif: str) -> str:
    """NIF/CIF comparable: mayúsculas, sin separadores y sin el prefijo ES del NIF-IVA.

    Los valores de relleno ("N/A", "-", "00000000", "X") se tratan como vacíos:
    no tienen ninguna cifra distinta de cero o no llegan a LONGITUD_MINIMA_NIF
    caracteres. No se valida el formato español para no descartar NIF-IVA extranjeros.
    """
    if not nif:
        return ""
    limpio = re.sub(r"[^0-9A-Z]", "", sin_acentos(str(nif)).upper())
    if limpio.startswith("ES") and len(limpio) == 11:
        limpio = limpio[2:]
    if len(limpio) < LONGITUD_MINIMA_NIF or not re.search(r"[1-9]", limpio):
        return ""
    return limpio


def normalizar_nombre(nombre: str) -> str:
    """Nombre comparable: sin forma jurídica, puntuación, mayúsculas ni acentos.

    "Proveedor Ejemplo, S.L." y "PROVEEDOR EJEMPLO SL" dan "proveedor ejemplo".
    """
    if not nombre:
        return ""
    texto = sin_acentos(str(nombre)).lower()
    for frase in _FRASES_JURIDICAS:
        texto = texto.replace(frase, " ")
    texto = texto.replace(".", "")              # "S.L." -> "SL"
    texto = re.sub(r"[^0-9a-z]+", " ", texto)
    # Une letras sueltas consecutivas ("s l u" -> "slu") para reconocer "S. L. U."
    unidas: list[str] = []
    sueltas: list[bool] = []
    for ficha in texto.split():
        if len(ficha) == 1 and ficha.isalpha() and sueltas and sueltas[-1]:
            unidas[-1] += ficha
        else:
            unidas.append(ficha)
            sueltas.append(len(ficha) == 1 and ficha.isalpha())
    return " ".join(f for f in unidas if f not in _FORMAS_JURIDICAS)


def a_decimal(valor) -> Decimal:
    """Convierte cadenas ("121.00", "1.234,56"), números o None en Decimal."""
    if valor is None or valor == "":
        return CERO
    if isinstance(valor, bool):
        return CERO
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(str(valor))
    texto = str(valor).strip().replace("€", "").replace(" ", "").replace(" ", "")
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return CERO


@lru_cache(maxsize=None)
def zona(nombre: str = ZONA_HORARIA) -> ZoneInfo | timezone:
    """Zona horaria por nombre IANA; UTC si el sistema no la conoce."""
    try:
        return ZoneInfo(nombre or ZONA_HORARIA)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def zona_valida(nombre: str) -> bool:
    try:
        ZoneInfo(nombre)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def a_fecha(valor, zona_horaria: str = ZONA_HORARIA) -> date | None:
    """Convierte "2026-01-15", "2026-01-15T10:30:00Z", "15/01/2026" o un timestamp Unix (s) en date.

    Los timestamps se pasan a fecha en la zona horaria de la empresa (por defecto
    Europe/Madrid): las 00:00 del 15/01 en Madrid son el 15/01, no el 14/01 de UTC.
    """
    if valor is None or valor == "" or isinstance(valor, bool):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):
        segundos = float(valor)
        if segundos > 1e11:          # milisegundos
            segundos /= 1000
        return datetime.fromtimestamp(segundos, tz=zona(zona_horaria)).date()
    texto = str(valor).strip()
    if re.fullmatch(r"\d{9,13}", texto):
        return a_fecha(int(texto), zona_horaria)
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        pass
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def euros(importe: Decimal) -> str:
    """Formato español: 1.234,56 €."""
    signo = "-" if importe < 0 else ""
    entero, _, dec = f"{abs(importe):.2f}".partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{dec} €"


def importe_moneda(importe: Decimal, moneda: str = MONEDA_BASE) -> str:
    """Como euros(), pero con el código de la moneda si no es EUR: "1.000,00 USD"."""
    texto = euros(importe)
    if es_moneda_base(moneda):
        return texto
    return texto[:-2] + " " + str(moneda).upper()


def es_moneda_base(moneda: str) -> bool:
    return (moneda or MONEDA_BASE).strip().upper() == MONEDA_BASE


def precio(importe: Decimal) -> str:
    """Precio unitario con 2 a 4 decimales, formato español, sin símbolo."""
    texto = f"{importe:.4f}".rstrip("0")
    entero, _, dec = texto.partition(".")
    dec = (dec + "00")[: max(2, len(dec))]
    return f"{entero},{dec}"
