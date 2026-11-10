"""Cliente de Holded: solo lectura, reintentos y la clave nunca visible."""

import json
import urllib.request

import pytest

from revision_compras import holded
from revision_compras.holded import ClienteHolded, ErrorHolded, MetodoNoPermitido, Respuesta

CLAVE = "clave-ficticia-de-prueba-0123456789"


class TransporteFalso:
    """Devuelve respuestas preparadas y guarda cada petición recibida."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.peticiones = []

    def __call__(self, metodo, url, cabeceras, timeout):
        self.peticiones.append((metodo, url, dict(cabeceras)))
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(datos, cabeceras=None):
    return Respuesta(200, cabeceras or {}, json.dumps(datos).encode())


def cliente(transporte, **kw):
    esperas = []
    c = ClienteHolded(CLAVE, transporte=transporte, dormir=esperas.append, reloj=lambda: 0.0, **kw)
    return c, esperas


# ------------------------------------------------------------ solo lectura

@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE", "post", "HEAD", "OPTIONS"])
def test_cualquier_metodo_distinto_de_get_lanza_excepcion_sin_tocar_la_red(metodo):
    t = TransporteFalso([])
    c, _ = cliente(t)
    with pytest.raises(MetodoNoPermitido):
        c.peticion(metodo, "/api/v2/purchases")
    assert t.peticiones == []


def test_el_cliente_no_tiene_metodos_de_escritura():
    for nombre in ("post", "put", "patch", "delete", "crear", "actualizar", "borrar"):
        assert not hasattr(ClienteHolded, nombre)


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
def test_el_transporte_real_tambien_rechaza_metodos_de_escritura(metodo, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("No debería abrir ninguna conexión")

    monkeypatch.setattr(urllib.request, "build_opener", prohibido)
    with pytest.raises(MetodoNoPermitido):
        holded.transporte_urllib(metodo, "https://api.holded.com/api/v2/purchases", {}, 5)


def test_solo_https():
    with pytest.raises(ErrorHolded):
        ClienteHolded(CLAVE, base_url="http://api.holded.com")
    with pytest.raises(ErrorHolded):
        holded.transporte_urllib("GET", "http://api.holded.com/x", {}, 5)


def test_todas_las_peticiones_de_una_descarga_son_get():
    t = TransporteFalso([
        ok({"items": [{"id": "1"}], "has_more": False, "cursor": None}),
        ok({"items": [], "has_more": False, "cursor": None}),
        ok({"items": [{"id": "c"}], "has_more": False, "cursor": None}),
    ])
    c, _ = cliente(t)
    c.compras("2026-01-01")
    c.abonos("2026-01-01")
    c.contactos()
    assert {m for m, _, _ in t.peticiones} == {"GET"}


# -------------------------------------------------------------- peticiones

def test_v2_usa_bearer_y_rutas_oficiales_con_paginacion_por_cursor():
    t = TransporteFalso([
        ok({"items": [{"id": "a"}, {"id": "b"}], "has_more": True, "cursor": "pag2"}),
        ok({"items": [{"id": "c"}], "has_more": False, "cursor": None}),
    ])
    c, _ = cliente(t)
    compras = c.compras("2026-01-01")
    assert [x["id"] for x in compras] == ["a", "b", "c"]
    metodo, url1, cab = t.peticiones[0]
    assert url1.startswith("https://api.holded.com/api/v2/purchases?")
    assert "start_date=2026-01-01" in url1 and "limit=200" in url1 and "cursor" not in url1
    assert "cursor=pag2" in t.peticiones[1][1]
    assert cab["Authorization"] == f"Bearer {CLAVE}"
    assert CLAVE not in url1


def test_rutas_de_abonos_y_contactos_v2():
    t = TransporteFalso([ok({"items": [], "has_more": False}), ok({"items": [], "has_more": False})])
    c, _ = cliente(t)
    c.abonos("2026-01-01")
    c.contactos()
    assert "/api/v2/purchase-refunds?" in t.peticiones[0][1]
    assert "/api/v2/contacts?" in t.peticiones[1][1] and "limit=100" in t.peticiones[1][1]


def test_v1_usa_cabecera_key_y_tipo_purchase():
    t = TransporteFalso([ok([{"id": "x"}])])
    c, _ = cliente(t, version="v1")
    assert c.compras("2026-01-01") == [{"id": "x"}]
    _, url, cab = t.peticiones[0]
    assert "/api/invoicing/v1/documents/purchase?" in url and "starttmp=" in url
    assert cab["key"] == CLAVE and "Authorization" not in cab


def test_cursor_repetido_no_provoca_bucle_infinito():
    pagina = ok({"items": [{"id": "a"}], "has_more": True, "cursor": "mismo"})
    t = TransporteFalso([pagina, pagina, pagina])
    c, _ = cliente(t)
    assert len(c.compras()) == 2


# ------------------------------------------------------------- reintentos

def test_429_respeta_retry_after_y_reintenta():
    t = TransporteFalso([
        Respuesta(429, {"Retry-After": "7"}, b'{"title":"Rate limit exceeded"}'),
        ok({"items": [], "has_more": False}),
    ])
    c, esperas = cliente(t)
    c.compras()
    assert 7.0 in esperas
    assert len(t.peticiones) == 2


def test_5xx_reintenta_con_espera_exponencial_y_acaba_fallando():
    t = TransporteFalso([Respuesta(503, {}, b"")] * 4)
    c, esperas = cliente(t, max_reintentos=3, intervalo_minimo=0)
    with pytest.raises(ErrorHolded, match="reintentos"):
        c.compras()
    assert len(t.peticiones) == 4
    assert esperas == sorted(esperas) and len(esperas) == 3


def test_429_con_espera_enorme_cupo_mensual_falla_con_mensaje_claro():
    t = TransporteFalso([Respuesta(429, {"Retry-After": "86400"}, b"")])
    c, _ = cliente(t)
    with pytest.raises(ErrorHolded, match="límite de peticiones"):
        c.compras()


def test_cupo_por_minuto_agotado_espera_al_reinicio():
    t = TransporteFalso([ok({"items": [], "has_more": False},
                            {"X-RateLimit-Remaining": "0", "X-RateLimit-Window": "minute"})])
    c, esperas = cliente(t)
    c.compras()
    assert esperas and esperas[-1] >= 1


def test_intervalo_minimo_entre_peticiones():
    t = TransporteFalso([ok({"items": [], "has_more": False})] * 2)
    esperas = []
    c = ClienteHolded(CLAVE, transporte=t, dormir=esperas.append, reloj=lambda: 100.0, intervalo_minimo=1.0)
    c.compras()
    c.abonos()
    assert esperas == [1.0]


def test_error_de_red_reintenta():
    t = TransporteFalso([OSError("caída"), ok({"items": [], "has_more": False})])
    c, _ = cliente(t)
    assert c.compras() == []


# ------------------------------------------------------- clave nunca visible

@pytest.mark.parametrize("estado", [400, 401, 403, 404, 302])
def test_los_errores_no_muestran_la_clave_aunque_la_api_la_devuelva(estado):
    cuerpo = json.dumps({"detail": f"token {CLAVE} no válido"}).encode()
    t = TransporteFalso([Respuesta(estado, {}, cuerpo)])
    c, _ = cliente(t)
    with pytest.raises(ErrorHolded) as e:
        c.compras()
    assert CLAVE not in str(e.value)
    assert CLAVE not in repr(e.value)


def test_error_de_red_no_muestra_la_clave():
    t = TransporteFalso([OSError(f"fallo con {CLAVE}")] * 2)
    c, _ = cliente(t, max_reintentos=1)
    with pytest.raises(ErrorHolded) as e:
        c.compras()
    assert CLAVE not in str(e.value)


def test_repr_y_registro_no_muestran_la_clave():
    mensajes = []
    t = TransporteFalso([Respuesta(500, {}, b""), ok({"items": [], "has_more": False})])
    c = ClienteHolded(CLAVE, transporte=t, dormir=lambda s: None, registrar=mensajes.append)
    c.compras()
    assert CLAVE not in repr(c) and CLAVE not in str(c)
    assert mensajes and all(CLAVE not in m for m in mensajes)


def test_mensaje_403_explica_los_permisos():
    t = TransporteFalso([Respuesta(403, {}, b"")])
    c, _ = cliente(t)
    with pytest.raises(ErrorHolded, match="Compras"):
        c.compras()


def test_5xx_con_retry_after_enorme_no_se_queda_dormido():
    t = TransporteFalso([Respuesta(503, {"Retry-After": "86400"}, b"")])
    c, esperas = cliente(t)
    with pytest.raises(ErrorHolded, match="no está disponible"):
        c.compras()
    assert esperas == [] and len(t.peticiones) == 1


def test_v1_starttmp_es_la_medianoche_de_madrid():
    t = TransporteFalso([ok([])])
    c, _ = cliente(t, version="v1")
    c.compras("2026-01-15")
    # 00:00 del 15/01/2026 en Europe/Madrid = 23:00 UTC del 14/01
    assert "starttmp=1768431600" in t.peticiones[0][1]


def test_v1_starttmp_con_otra_zona_horaria():
    t = TransporteFalso([ok([])])
    c, _ = cliente(t, version="v1", zona_horaria="Atlantic/Canary")
    c.compras("2026-01-15")
    assert "starttmp=1768435200" in t.peticiones[0][1]     # Canarias = UTC en invierno
