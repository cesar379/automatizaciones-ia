"""Cliente de la API de Holded de SOLO LECTURA.

Garantías:
- Solo existe el método GET. Cualquier otro método lanza ``MetodoNoPermitido``
  antes de tocar la red, tanto en el cliente como en el transporte HTTP.
- Solo HTTPS y sin seguir redirecciones (la clave nunca sale hacia otro host).
- La clave nunca aparece en ``repr``, mensajes de error ni registros.
- Reintenta ante 429 y errores 5xx respetando ``Retry-After`` y con espera
  exponencial; deja un intervalo mínimo entre peticiones.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_URL = "https://api.holded.com"
METODOS_PERMITIDOS = frozenset({"GET"})

# Rutas de la API (contrato verificado en la documentación oficial)
V2_COMPRAS = "/api/v2/purchases"
V2_ABONOS = "/api/v2/purchase-refunds"
V2_CONTACTOS = "/api/v2/contacts"
V1_DOCUMENTOS = "/api/invoicing/v1/documents/{tipo}"
V1_CONTACTOS = "/api/invoicing/v1/contacts"


class ErrorHolded(Exception):
    """Error al leer de Holded. El mensaje nunca contiene la clave."""


class MetodoNoPermitido(ErrorHolded):
    """Se ha intentado una operación distinta de GET."""


@dataclass
class Respuesta:
    estado: int
    cabeceras: dict
    cuerpo: bytes


Transporte = Callable[[str, str, dict, float], Respuesta]


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise urllib.error.HTTPError(req.full_url, code, "Redirección no permitida", headers, fp)


def transporte_urllib(metodo: str, url: str, cabeceras: dict, timeout: float) -> Respuesta:
    """Transporte HTTP real con la librería estándar. Solo admite GET."""
    if metodo.upper() not in METODOS_PERMITIDOS:
        raise MetodoNoPermitido(f"Método {metodo} no permitido: la revisión de compras solo lee (GET).")
    if not url.startswith("https://"):
        raise ErrorHolded("Solo se permiten conexiones HTTPS.")
    peticion = urllib.request.Request(url, method="GET")
    for nombre, valor in cabeceras.items():
        # Cabecera no reenviable: si hubiera redirección no viajaría a otro host
        peticion.add_unredirected_header(nombre, valor)
    abridor = urllib.request.build_opener(_SinRedirecciones())
    try:
        with abridor.open(peticion, timeout=timeout) as r:
            return Respuesta(r.status, dict(r.headers.items()), r.read())
    except urllib.error.HTTPError as e:
        cuerpo = b""
        try:
            cuerpo = e.read() or b""
        except Exception:  # pragma: no cover - cuerpo ilegible
            pass
        return Respuesta(e.code, dict(e.headers.items()) if e.headers else {}, cuerpo)


def _ocultar(texto: str, secreto: str) -> str:
    if secreto and texto:
        texto = texto.replace(secreto, "***")
    return texto


def _cabecera(cabeceras: dict, nombre: str) -> str | None:
    for k, v in cabeceras.items():
        if k.lower() == nombre.lower():
            return v
    return None


class ClienteHolded:
    """Cliente de solo lectura. ``version`` es "v2" (recomendada) o "v1" (antigua)."""

    def __init__(
        self,
        clave: str,
        version: str = "v2",
        base_url: str = BASE_URL,
        transporte: Transporte | None = None,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
        intervalo_minimo: float = 1.0,
        max_reintentos: int = 5,
        espera_maxima: float = 120.0,
        timeout: float = 60.0,
        registrar: Callable[[str], None] | None = None,
        zona_horaria: str = "Europe/Madrid",
    ) -> None:
        if not clave:
            raise ErrorHolded("Falta la clave de la API de Holded.")
        if version not in ("v1", "v2"):
            raise ErrorHolded('La versión de la API debe ser "v1" o "v2".')
        if not base_url.startswith("https://"):
            raise ErrorHolded("Solo se permiten conexiones HTTPS.")
        self.__clave = clave
        self.version = version
        self.base_url = base_url.rstrip("/")
        self._transporte = transporte or transporte_urllib
        self._dormir = dormir
        self._reloj = reloj
        self._intervalo = intervalo_minimo
        self._max_reintentos = max_reintentos
        self._espera_maxima = espera_maxima
        self._timeout = timeout
        self._registrar = registrar or (lambda _m: None)
        try:
            self._zona = ZoneInfo(zona_horaria)
        except (ZoneInfoNotFoundError, ValueError):
            raise ErrorHolded(f"Zona horaria desconocida: {zona_horaria}.") from None
        self._ultima = None
        self.peticiones = 0

    def __repr__(self) -> str:
        return f"ClienteHolded(version={self.version!r}, base_url={self.base_url!r}, clave=***)"

    # -- única puerta de salida a la red ---------------------------------
    def peticion(self, metodo: str, ruta: str, params: dict | None = None):
        """Hace una petición. Cualquier método distinto de GET se rechaza."""
        if str(metodo).upper() not in METODOS_PERMITIDOS:
            raise MetodoNoPermitido(
                f"Método {metodo} no permitido: la revisión de compras nunca modifica Holded (solo GET)."
            )
        return self._get(ruta, params)

    def get(self, ruta: str, params: dict | None = None):
        return self.peticion("GET", ruta, params)

    def _cabeceras(self) -> dict:
        if self.version == "v2":
            return {"Authorization": f"Bearer {self.__clave}", "Accept": "application/json"}
        return {"key": self.__clave, "Accept": "application/json"}

    def _esperar_turno(self) -> None:
        if self._ultima is not None:
            pendiente = self._intervalo - (self._reloj() - self._ultima)
            if pendiente > 0:
                self._dormir(pendiente)

    def _get(self, ruta: str, params: dict | None):
        consulta = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
        url = f"{self.base_url}{ruta}" + (f"?{consulta}" if consulta else "")
        descripcion = f"GET {ruta}"
        for intento in range(self._max_reintentos + 1):
            self._esperar_turno()
            try:
                respuesta = self._transporte("GET", url, self._cabeceras(), self._timeout)
            except MetodoNoPermitido:
                raise
            except Exception as e:  # red caída, timeout...
                self._ultima = self._reloj()
                if intento >= self._max_reintentos:
                    raise ErrorHolded(
                        f"No se pudo conectar con Holded ({descripcion}): {_ocultar(type(e).__name__, self.__clave)}."
                    ) from None
                self._dormir(self._espera_exponencial(intento))
                continue
            self._ultima = self._reloj()
            self.peticiones += 1
            estado = respuesta.estado

            if 200 <= estado < 300:
                self._respetar_cupo(respuesta.cabeceras)
                try:
                    return json.loads(respuesta.cuerpo.decode("utf-8") or "null")
                except (ValueError, UnicodeDecodeError):
                    raise ErrorHolded(f"Holded devolvió una respuesta que no es JSON ({descripcion}).") from None

            if estado == 429 or estado >= 500:
                espera = self._espera_reintento(respuesta, intento)
                if estado == 429 and espera > self._espera_maxima:
                    raise ErrorHolded(
                        "Se ha alcanzado el límite de peticiones de la API de Holded "
                        f"(hay que esperar {int(espera)} s; puede ser el cupo mensual del plan). "
                        "Consulta el uso en Configuración > Desarrolladores > Uso de la API "
                        "y vuelve a ejecutar más tarde, o usa --cache con lo ya descargado."
                    )
                if espera > self._espera_maxima:
                    raise ErrorHolded(
                        f"Holded no está disponible ahora (error {estado}) y pide esperar {int(espera)} s. "
                        "Vuelve a ejecutar más tarde, o usa --cache con lo ya descargado."
                    )
                if intento >= self._max_reintentos:
                    break
                self._registrar(f"Holded respondió {estado}; reintento en {espera:.0f} s.")
                self._dormir(espera)
                continue

            raise ErrorHolded(self._mensaje_error(estado, respuesta, descripcion))

        raise ErrorHolded(f"Holded sigue sin responder correctamente tras varios reintentos ({descripcion}).")

    def _espera_exponencial(self, intento: int) -> float:
        return min(self._espera_maxima, (2 ** intento) + random.uniform(0, 1))

    def _espera_reintento(self, respuesta: Respuesta, intento: int) -> float:
        retry_after = _cabecera(respuesta.cabeceras, "Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self._espera_exponencial(intento)

    def _respetar_cupo(self, cabeceras: dict) -> None:
        """Si quedan 0 peticiones en la ventana por minuto, espera al reinicio."""
        restantes = _cabecera(cabeceras, "X-RateLimit-Remaining")
        ventana = (_cabecera(cabeceras, "X-RateLimit-Window") or "minute").lower()
        reinicio = _cabecera(cabeceras, "X-RateLimit-Reset")
        if restantes is None or ventana != "minute":
            return
        try:
            if int(float(restantes)) > 0:
                return
            espera = float(reinicio) - time.time() if reinicio else 60.0
        except ValueError:
            espera = 60.0
        espera = min(max(espera, 1.0), self._espera_maxima)
        self._registrar(f"Cupo por minuto agotado; espera de {espera:.0f} s.")
        self._dormir(espera)

    def _mensaje_error(self, estado: int, respuesta: Respuesta, descripcion: str) -> str:
        detalle = ""
        try:
            datos = json.loads(respuesta.cuerpo.decode("utf-8"))
            if isinstance(datos, dict):
                detalle = str(datos.get("detail") or datos.get("title") or datos.get("message") or "")
        except Exception:
            pass
        detalle = _ocultar(detalle, self.__clave)[:200]
        if estado == 401:
            base = (
                "Holded rechaza la clave (401): falta o no es válida. Revisa HOLDED_API_KEY "
                f"y que sea una clave {self.version} (las claves v1 y v2 son distintas)."
            )
        elif estado == 403:
            base = (
                "La clave no tiene permiso para esta consulta (403). Crea un API Token con lectura "
                "de Compras y de Contactos (scopes accounting:purchases.read y contacts:contacts.read)."
            )
        elif estado == 404:
            base = f"Holded no encuentra el recurso (404) en {descripcion}."
        elif 300 <= estado < 400:
            base = f"Holded respondió con una redirección ({estado}) que no se sigue por seguridad."
        else:
            base = f"Holded respondió con error {estado} en {descripcion}."
        return base + (f" Detalle: {detalle}" if detalle else "")

    # -- lecturas de alto nivel ------------------------------------------
    def _paginar(self, ruta: str, params: dict, limite: int) -> Iterator[dict]:
        cursor = None
        vistos = set()
        while True:
            pagina = self.get(ruta, {**params, "limit": limite, "cursor": cursor})
            elementos, cursor, hay_mas = _desempaquetar(pagina)
            yield from elementos
            if not hay_mas or not cursor or cursor in vistos:
                return
            vistos.add(cursor)

    def compras(self, desde: str | None = None) -> list[dict]:
        if self.version == "v2":
            return list(self._paginar(V2_COMPRAS, {"start_date": desde}, 200))
        return self._v1_documentos("purchase", desde)

    def abonos(self, desde: str | None = None) -> list[dict]:
        if self.version == "v2":
            return list(self._paginar(V2_ABONOS, {"start_date": desde}, 200))
        return self._v1_documentos("purchaserefund", desde)

    def contactos(self) -> list[dict]:
        if self.version == "v2":
            return list(self._paginar(V2_CONTACTOS, {}, 100))
        elementos, _, _ = _desempaquetar(self.get(V1_CONTACTOS))
        return elementos

    def _v1_documentos(self, tipo: str, desde: str | None) -> list[dict]:
        params = {"sort": "created-asc"}
        if desde:
            # Medianoche del primer día en la zona de la empresa, no en UTC: un
            # documento de las 00:00 en Madrid es de las 23:00 UTC del día anterior.
            inicio = datetime.fromisoformat(desde).replace(tzinfo=self._zona)
            params["starttmp"] = int(inicio.timestamp())
            params["endtmp"] = int(time.time())
        elementos, _, _ = _desempaquetar(self.get(V1_DOCUMENTOS.format(tipo=tipo), params))
        return elementos


def _desempaquetar(pagina) -> tuple[list[dict], str | None, bool]:
    """Admite {items, cursor, has_more} (v2), una lista (v1) u otras envolturas habituales."""
    if isinstance(pagina, list):
        return [e for e in pagina if isinstance(e, dict)], None, False
    if not isinstance(pagina, dict):
        return [], None, False
    elementos = None
    for clave in ("items", "data", "results", "documents", "contacts"):
        if isinstance(pagina.get(clave), list):
            elementos = pagina[clave]
            break
    if elementos is None:
        elementos = []
    cursor = pagina.get("cursor") or pagina.get("next_cursor") or pagina.get("nextCursor")
    hay_mas = pagina.get("has_more", pagina.get("hasMore"))
    if hay_mas is None:
        hay_mas = bool(cursor)
    return [e for e in elementos if isinstance(e, dict)], cursor, bool(hay_mas)
