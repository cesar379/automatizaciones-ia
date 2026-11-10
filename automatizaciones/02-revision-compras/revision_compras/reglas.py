"""Reglas de revisión de compras.

Todas son funciones puras: reciben documentos y contactos del modelo neutro
(``modelo.py``) y devuelven avisos. No saben nada de Holded ni de ningún otro
ERP, así que sirven igual para datos leídos de un archivo exportado.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from .modelo import ALTA, BAJA, CERO, MEDIA, ORDEN_PRIORIDAD, Aviso, Contacto, Documento, Linea
from .texto import (
    MONEDA_BASE,
    contiene_palabra,
    empieza_por_palabra,
    es_moneda_base,
    importe_moneda,
    mismo_numero_documento,
    normalizar_nif,
    normalizar_nombre,
    precio,
    texto_busqueda,
)

TIPO_DUPLICADO = "Posible duplicado"
TIPO_ABONO = "Abono o devolución pendiente"
TIPO_PRECIO = "Subida de precio"
TIPO_FICHA = "Ficha de proveedor errónea"
TIPO_MAL_REGISTRADO = "Documento mal registrado"
TIPOS = (TIPO_DUPLICADO, TIPO_ABONO, TIPO_PRECIO, TIPO_FICHA, TIPO_MAL_REGISTRADO)

PALABRAS_ABONO = (
    "abono", "devolver", "devolucion", "no se hace", "anular", "anulada",
    "erroneo", "error", "tienen que hacer",
)
# Palabras que en las líneas suelen ser nombres de producto (abono orgánico,
# abono de transporte): solo se buscan en la descripción y las notas.
PALABRAS_ABONO_SOLO_CABECERA = ("abono",)
PALABRAS_PRESUPUESTO = ("presupuesto", "proforma", "oferta")
# Conceptos cuyo importe varía en cada factura: no son una subida de precio.
CONCEPTOS_PRECIO_VARIABLE = (
    "porte", "transporte", "envio", "mensajeria", "energia", "electricidad", "consumo", "suministro",
)
ESTADOS_IGNORADOS = {"cancelled", "canceled", "cancelada", "anulada"}

TOLERANCIA = Decimal("0.01")
DIAS_DUPLICADO = 3
MESES_CUOTA_RECURRENTE = 3
FECHAS_IMPORTE_HABITUAL = 4


@dataclass(frozen=True)
class Parametros:
    nif_propio: str = ""
    umbral_subida_precio: Decimal = Decimal("5")      # en %
    palabras_abono: tuple[str, ...] = PALABRAS_ABONO
    palabras_abono_solo_cabecera: tuple[str, ...] = PALABRAS_ABONO_SOLO_CABECERA
    palabras_presupuesto: tuple[str, ...] = PALABRAS_PRESUPUESTO
    conceptos_precio_variable: tuple[str, ...] = CONCEPTOS_PRECIO_VARIABLE
    dias_duplicado: int = DIAS_DUPLICADO


# ---------------------------------------------------------------- utilidades

def clave_proveedor(doc: Documento) -> str:
    """Identifica al proveedor: su id en el ERP o, si no hay, su nombre normalizado.

    Devuelve "" si el documento no tiene proveedor: esos documentos no se
    comparan con otros (no son "del mismo proveedor").
    """
    if doc.proveedor_id:
        return f"id:{doc.proveedor_id}"
    nombre = normalizar_nombre(doc.proveedor_nombre)
    return f"nombre:{nombre}" if nombre else ""


def _moneda(doc: Documento) -> str:
    return (doc.moneda or MONEDA_BASE).strip().upper()


def _importe(total: Decimal, moneda: str) -> Decimal:
    """Importe en juego en euros: los importes en otra moneda no se suman (0)."""
    return abs(total) if es_moneda_base(moneda) else CERO


def _nota_moneda(moneda: str) -> str:
    if es_moneda_base(moneda):
        return ""
    return f" Importes en {moneda}: no se suman al importe en juego en euros."


def _activos(documentos: Iterable[Documento]) -> list[Documento]:
    return [d for d in documentos if (d.estado or "").lower() not in ESTADOS_IGNORADOS]


def _iguales(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCIA


def _mes(fecha: date | None) -> tuple[int, int] | None:
    return (fecha.year, fecha.month) if fecha else None


def _fecha_orden(doc: Documento) -> date:
    return doc.fecha or date.min


TOLERANCIA_ABONO = Decimal("0.02")   # 2 %: diferencias de redondeo, portes o recargos


def _cubre_importe(abono: Documento, compra: Documento) -> bool:
    """El abono es por el mismo importe que la compra (±2 %).

    Un abono mayor no cuenta: suele corresponder a otra compra del mismo proveedor.
    """
    if _moneda(abono) != _moneda(compra) or compra.total <= CERO:
        return False
    return abs(abs(abono.total) - compra.total) <= compra.total * TOLERANCIA_ABONO


def _abonos_posteriores(compra: Documento, abonos: Sequence[Documento]) -> list[Documento]:
    """Abonos del mismo proveedor con fecha igual o posterior a la compra."""
    clave = clave_proveedor(compra)
    if not clave:
        return []
    return [
        a for a in abonos
        if clave_proveedor(a) == clave
        and (compra.fecha is None or a.fecha is None or a.fecha >= compra.fecha)
    ]


def ordenar_avisos(avisos: Iterable[Aviso]) -> list[Aviso]:
    return sorted(
        avisos,
        key=lambda a: (ORDEN_PRIORIDAD.get(a.prioridad, 9), -a.importe, a.tipo, a.proveedor, a.documentos),
    )


# ------------------------------------------------------- 1. posible duplicado

def _en(importe: Decimal, importes: set[Decimal]) -> bool:
    return any(_iguales(abs(importe), i) for i in importes)


def _motivo_duplicado(
    a: Documento,
    b: Documento,
    recurrentes: set[Decimal],
    habituales: set[Decimal],
    dias: int,
) -> tuple[str, bool] | None:
    """Devuelve (motivo, por_numero) si a y b parecen el mismo documento."""
    if mismo_numero_documento(a.numero, b.numero):
        # Numeraciones que se reinician cada año: el mismo número en años
        # distintos solo es duplicado si el importe coincide y no es una cuota
        # que el proveedor factura todos los meses (alquiler 1..12 cada año).
        mismo_anio = a.fecha is None or b.fecha is None or a.fecha.year == b.fecha.year
        if mismo_anio or (_iguales(a.total, b.total) and not _en(a.total, recurrentes)):
            return f"mismo número de documento ({a.numero} / {b.numero})", True
    if a.total != CERO and _iguales(a.total, b.total) and a.fecha and b.fecha:
        distancia = abs((a.fecha - b.fecha).days)
        if distancia <= dias:
            if distancia > 0 and _en(a.total, habituales):
                return None     # pedido fijo: el proveedor factura ese importe muchas veces
            if _mes(a.fecha) != _mes(b.fecha) and _en(a.total, recurrentes):
                return None     # cuota periódica (alquiler, renting, teléfono...)
            texto_dias = "la misma fecha" if distancia == 0 else f"{distancia} día(s) de diferencia"
            return f"mismo importe ({importe_moneda(a.total, _moneda(a))}) con {texto_dias}", False
    return None


def _importes_recurrentes(docs: Sequence[Documento]) -> set[Decimal]:
    """Importes que el proveedor factura en al menos MESES_CUOTA_RECURRENTE meses distintos."""
    meses_por_importe: dict[Decimal, set] = defaultdict(set)
    for d in docs:
        if d.fecha and d.total != CERO:
            meses_por_importe[abs(d.total).quantize(TOLERANCIA)].add(_mes(d.fecha))
    return {imp for imp, meses in meses_por_importe.items() if len(meses) >= MESES_CUOTA_RECURRENTE}


def _importes_habituales(docs: Sequence[Documento]) -> set[Decimal]:
    """Importes que el proveedor factura en al menos FECHAS_IMPORTE_HABITUAL fechas distintas (pedidos fijos)."""
    fechas_por_importe: dict[Decimal, set] = defaultdict(set)
    for d in docs:
        if d.fecha and d.total != CERO:
            fechas_por_importe[abs(d.total).quantize(TOLERANCIA)].add(d.fecha)
    return {imp for imp, fechas in fechas_por_importe.items() if len(fechas) >= FECHAS_IMPORTE_HABITUAL}


def regla_duplicados(documentos: Sequence[Documento], params: Parametros = Parametros()) -> list[Aviso]:
    activos = _activos(documentos)
    abonos = [d for d in activos if d.es_abono]
    avisos: list[Aviso] = []
    dias = params.dias_duplicado

    # Solo se comparan documentos del mismo tipo, proveedor y moneda.
    grupos: dict[tuple[str, str, str], list[Documento]] = defaultdict(list)
    for d in activos:
        clave = clave_proveedor(d)
        if clave:
            grupos[(d.tipo, clave, _moneda(d))].append(d)

    for (tipo, _, moneda), docs in grupos.items():
        docs = sorted(docs, key=lambda d: (_fecha_orden(d), d.numero, d.id))
        recurrentes = _importes_recurrentes(docs)
        habituales = _importes_habituales(docs)
        # Unión de pares duplicados en grupos (A=B y B=C -> un solo aviso A, B, C).
        # Por importe (caso b) solo se une si todo el grupo cabe en `dias` días:
        # así no se encadenan entregas periódicas separadas por semanas.
        padre = list(range(len(docs)))
        primera = [d.fecha for d in docs]
        ultima = [d.fecha for d in docs]

        def raiz(i: int) -> int:
            while padre[i] != i:
                padre[i] = padre[padre[i]]
                i = padre[i]
            return i

        def unir(i: int, j: int, limitar: bool) -> int | None:
            ri, rj = raiz(i), raiz(j)
            if ri == rj:
                return ri
            inicios = [f for f in (primera[ri], primera[rj]) if f]
            finales = [f for f in (ultima[ri], ultima[rj]) if f]
            inicio = min(inicios, default=None)
            fin = max(finales, default=None)
            if limitar and inicio and fin and (fin - inicio).days > dias:
                return None
            padre[rj] = ri
            primera[ri], ultima[ri] = inicio, fin
            return ri

        motivos: dict[int, list[str]] = defaultdict(list)
        for i in range(len(docs)):
            for j in range(i + 1, len(docs)):
                resultado = _motivo_duplicado(docs[i], docs[j], recurrentes, habituales, dias)
                if resultado:
                    motivo, por_numero = resultado
                    r = unir(i, j, limitar=not por_numero)
                    if r is not None:
                        motivos[r].append(motivo)

        conjuntos: dict[int, list[int]] = defaultdict(list)
        for i in range(len(docs)):
            conjuntos[raiz(i)].append(i)

        for r, indices in conjuntos.items():
            if len(indices) < 2:
                continue
            grupo = [docs[i] for i in indices]
            todos_motivos = sorted({m for i in indices for m in motivos.get(i, [])})
            importe = sum((_importe(d.total, moneda) for d in grupo[1:]), CERO)
            prioridad = ALTA
            detalle = (
                f"{len(grupo)} documentos del mismo proveedor: " + "; ".join(todos_motivos) + "."
                + _nota_moneda(moneda)
            )
            accion = "Comprobar si es la misma factura registrada dos veces y, si lo es, eliminar o rectificar la copia en el ERP."
            if tipo != "abono":
                anulacion = [
                    a for a in abonos
                    if _moneda(a) == moneda and any(
                        clave_proveedor(a) == clave_proveedor(d)
                        and _iguales(abs(a.total), abs(d.total))
                        and (d.fecha is None or a.fecha is None or a.fecha >= d.fecha)
                        for d in grupo
                    )
                ]
                if anulacion:
                    prioridad = BAJA
                    detalle += f" Posiblemente anulada por abono ({', '.join(a.referencia for a in anulacion)})."
                    accion = "Confirmar que el abono anula la copia duplicada; si es así, no hace falta hacer nada."
            avisos.append(Aviso(
                prioridad=prioridad,
                tipo=TIPO_DUPLICADO,
                proveedor=grupo[0].proveedor_nombre,
                documentos=", ".join(d.referencia for d in grupo),
                fecha=max((d.fecha for d in grupo if d.fecha), default=None),
                importe=importe,
                detalle=detalle,
                accion=accion,
                ids=tuple(d.id for d in grupo),
            ))
    return avisos


# ------------------------------------------- 2. abono o devolución pendiente

def _linea_positiva(linea: Linea) -> bool:
    """Las líneas en negativo (devolución de envases, descuento) ya están descontadas en la factura."""
    return linea.precio >= CERO and linea.unidades >= CERO


def texto_documento(doc: Documento, incluir_lineas: bool = True) -> str:
    """Descripción y notas del documento y, si se pide, el texto de sus líneas en positivo."""
    partes = [doc.descripcion, doc.notas]
    if incluir_lineas:
        partes += texto_lineas(doc)
    return " | ".join(p for p in partes if p)


def texto_lineas(doc: Documento) -> list[str]:
    partes: list[str] = []
    for linea in doc.lineas:
        if _linea_positiva(linea):
            partes.extend([linea.nombre, linea.descripcion])
    return [p for p in partes if p]


def _palabra_abono(doc: Documento, params: Parametros) -> str | None:
    palabra = contiene_palabra(texto_documento(doc, incluir_lineas=False), params.palabras_abono)
    if palabra:
        return palabra
    solo_cabecera = {texto_busqueda(p) for p in params.palabras_abono_solo_cabecera}
    en_lineas = [p for p in params.palabras_abono if texto_busqueda(p) not in solo_cabecera]
    return contiene_palabra(" | ".join(texto_lineas(doc)), en_lineas)


def regla_abono_pendiente(documentos: Sequence[Documento], params: Parametros = Parametros()) -> list[Aviso]:
    activos = _activos(documentos)
    abonos = [d for d in activos if d.es_abono]
    avisos = []
    for compra in activos:
        # Los abonos y las compras en negativo ya son el abono (la regla 5a avisa
        # si una rectificativa se ha registrado como compra).
        if compra.es_abono or compra.total < CERO:
            continue
        palabra = _palabra_abono(compra, params)
        if not palabra:
            continue
        moneda = _moneda(compra)
        posteriores = _abonos_posteriores(compra, abonos)
        # Solo se da por probablemente resuelto si un abono posterior cubre el importe;
        # otros abonos del mismo proveedor pueden corresponder a otras compras.
        posteriores = [a for a in posteriores if _cubre_importe(a, compra)]
        if posteriores:
            avisos.append(Aviso(
                prioridad=BAJA,
                tipo=TIPO_ABONO,
                proveedor=compra.proveedor_nombre,
                documentos=compra.referencia,
                fecha=compra.fecha,
                importe=_importe(compra.total, moneda),
                detalle=(
                    f'El texto de la compra contiene "{palabra}" y hay abono(s) posteriores del proveedor '
                    f"({', '.join(a.referencia for a in posteriores)}). Comprobar que el abono cubre esta compra."
                    + _nota_moneda(moneda)
                ),
                accion="Comprobar que el abono cubre esta compra (importe y conceptos).",
                ids=(compra.id,) + tuple(a.id for a in posteriores),
            ))
        else:
            avisos.append(Aviso(
                prioridad=ALTA,
                tipo=TIPO_ABONO,
                proveedor=compra.proveedor_nombre,
                documentos=compra.referencia,
                fecha=compra.fecha,
                importe=_importe(compra.total, moneda),
                detalle=(
                    f'El texto de la compra contiene "{palabra}" y no hay ningún abono posterior del proveedor '
                    "por un importe que la cubra." + _nota_moneda(moneda)
                ),
                accion="Reclamar el abono o la devolución al proveedor, o anotar por qué no procede.",
                ids=(compra.id,),
            ))
    return avisos


# --------------------------------------------- 3. subida de precio de compra

def _clave_producto(linea) -> str:
    if linea.sku and linea.sku.strip():
        return "sku:" + texto_busqueda(linea.sku)
    nombre = texto_busqueda(linea.nombre) or texto_busqueda(linea.descripcion)
    return "nombre:" + nombre if nombre else ""


def _resumen_en_una_linea(doc: Documento) -> bool:
    """Factura registrada como una sola línea de 1 unidad con todo el importe.

    Es lo habitual cuando un escáner o una persona resume la factura en vez de
    copiar sus productos: su «precio» es el total y no se puede comparar.
    """
    if len(doc.lineas) != 1:
        return False
    unica = doc.lineas[0]
    return (
        unica.unidades == Decimal("1")
        and not (unica.sku or "").strip()
        and doc.subtotal > CERO
        and abs(unica.precio_neto - doc.subtotal) <= TOLERANCIA
    )


def _precio_variable(linea: Linea, params: Parametros) -> bool:
    """Portes, energía, consumos...: el importe cambia en cada factura y no es una subida de tarifa."""
    texto = f"{linea.nombre} | {linea.descripcion}"
    return bool(contiene_palabra(texto, params.conceptos_precio_variable))


def regla_subida_precio(documentos: Sequence[Documento], params: Parametros = Parametros()) -> list[Aviso]:
    compras = [d for d in _activos(documentos) if not d.es_abono and d.fecha and clave_proveedor(d)]
    # (proveedor, moneda, producto) -> lista de (fecha, doc, precio_neto_medio, unidades, nombre)
    historico: dict[tuple[str, str, str], list] = defaultdict(list)
    for doc in compras:
        if _resumen_en_una_linea(doc):
            continue
        por_producto: dict[str, list] = defaultdict(list)
        for linea in doc.lineas:
            # Fuera: precio o unidades no positivos, regalos con 100 % de descuento
            # y conceptos de importe variable.
            if linea.precio <= CERO or linea.unidades <= CERO or linea.precio_neto <= CERO:
                continue
            if _precio_variable(linea, params):
                continue
            clave = _clave_producto(linea)
            if clave:
                por_producto[clave].append(linea)
        for clave, lineas in por_producto.items():
            if len({l.precio_neto for l in lineas}) > 1 and not clave.startswith("sku:"):
                # Mismo nombre con precios distintos en una factura: es un concepto
                # genérico ("Servicios", "Factura de ..."), no un producto comparable.
                continue
            unidades = sum((l.unidades for l in lineas), CERO)
            neto = sum((l.precio_neto * l.unidades for l in lineas), CERO) / unidades
            nombre = lineas[0].nombre or lineas[0].descripcion or lineas[0].sku
            historico[(clave_proveedor(doc), _moneda(doc), clave)].append((doc.fecha, doc, neto, unidades, nombre))

    umbral = Decimal(str(params.umbral_subida_precio))
    avisos = []
    for (_, moneda, _), compras_producto in historico.items():
        simbolo = "€" if es_moneda_base(moneda) else moneda
        compras_producto.sort(key=lambda c: (c[0], c[1].numero, c[1].id))
        for anterior, actual in zip(compras_producto, compras_producto[1:]):
            _, doc_ant, neto_ant, _, _ = anterior
            fecha, doc, neto, unidades, nombre = actual
            if neto_ant <= CERO or neto <= neto_ant:
                continue
            subida = (neto - neto_ant) / neto_ant * Decimal("100")
            if subida < umbral:
                continue
            diferencia = ((neto - neto_ant) * unidades).quantize(TOLERANCIA)
            avisos.append(Aviso(
                prioridad=MEDIA,
                tipo=TIPO_PRECIO,
                proveedor=doc.proveedor_nombre,
                documentos=f"{doc.referencia} (anterior: {doc_ant.referencia})",
                fecha=fecha,
                importe=_importe(diferencia, moneda),
                detalle=(
                    f'"{nombre}": precio neto unitario {precio(neto_ant)} {simbolo} → {precio(neto)} {simbolo} '
                    f"(+{subida.quantize(Decimal('0.1'))} %) respecto a la compra del "
                    f"{doc_ant.fecha.strftime('%d/%m/%Y')}; {precio(unidades)} unidades."
                    + _nota_moneda(moneda)
                ),
                accion="Comprobar la tarifa pactada con el proveedor y reclamar la diferencia si no estaba acordada.",
                ids=(doc.id, doc_ant.id),
            ))
    return avisos


# --------------------------------------------- 4. ficha de proveedor errónea

def regla_fichas_proveedor(
    documentos: Sequence[Documento],
    contactos: Sequence[Contacto],
    params: Parametros = Parametros(),
) -> list[Aviso]:
    activos = _activos(documentos)
    # Solo compras: los abonos no cuentan como compras ni suman al importe.
    compras_por_contacto: dict[str, list[Documento]] = defaultdict(list)
    for d in activos:
        if d.proveedor_id and not d.es_abono:
            compras_por_contacto[d.proveedor_id].append(d)

    proveedores = [c for c in contactos if c.es_proveedor or c.id in compras_por_contacto]
    avisos = []

    def total_compras(contacto_id: str) -> Decimal:
        """Total neto de las compras en euros (una compra en negativo resta)."""
        total = sum(
            (d.total for d in compras_por_contacto.get(contacto_id, []) if es_moneda_base(_moneda(d))), CERO
        )
        return max(total, CERO)

    def n_compras(contacto_id: str) -> int:
        return len(compras_por_contacto.get(contacto_id, []))

    # a) NIF propio en una ficha de proveedor
    nif_propio = normalizar_nif(params.nif_propio)
    if nif_propio:
        for c in proveedores:
            if normalizar_nif(c.nif) == nif_propio:
                avisos.append(Aviso(
                    prioridad=ALTA,
                    tipo=TIPO_FICHA,
                    proveedor=c.nombre or "(sin nombre de proveedor)",
                    documentos=f"{n_compras(c.id)} compra(s)",
                    fecha=None,
                    importe=total_compras(c.id),
                    detalle=f"La ficha del proveedor tiene el NIF de la propia empresa ({c.nif}).",
                    accion="Corregir el NIF en la ficha del proveedor con el que figura en sus facturas.",
                    ids=(c.id,),
                ))

    # b) Fichas repetidas por NIF o por nombre
    grupos: dict[frozenset, set[str]] = {}
    for etiqueta, funcion, campo in (("NIF", normalizar_nif, "nif"), ("nombre", normalizar_nombre, "nombre")):
        por_clave: dict[str, list[Contacto]] = defaultdict(list)
        for c in proveedores:
            clave = funcion(getattr(c, campo))
            if clave:
                por_clave[clave].append(c)
        for clave, fichas in por_clave.items():
            if len(fichas) < 2:
                continue
            ids = frozenset(c.id for c in fichas)
            grupos.setdefault(ids, set()).add(etiqueta)

    por_id = {c.id: c for c in proveedores}
    for ids, etiquetas in grupos.items():
        fichas = sorted((por_id[i] for i in ids), key=lambda c: (-n_compras(c.id), c.nombre, c.id))
        descripcion = "; ".join(
            f"{c.nombre or '(sin nombre)'} (NIF {c.nif or 'vacío'}, {n_compras(c.id)} compra(s))" for c in fichas
        )
        importe = sum((total_compras(c.id) for c in fichas[1:]), CERO)
        motivo = " y ".join(f"el mismo {e}" for e in sorted(etiquetas))
        avisos.append(Aviso(
            prioridad=MEDIA,
            tipo=TIPO_FICHA,
            proveedor=fichas[0].nombre or "(sin nombre de proveedor)",
            documentos=f"{len(fichas)} fichas",
            fecha=None,
            importe=importe,
            detalle=f"{len(fichas)} fichas de proveedor con {motivo}: {descripcion}.",
            accion="Unificar las fichas en una sola (o corregir el NIF o el nombre si son proveedores distintos).",
            ids=tuple(c.id for c in fichas),
        ))

    # c) Proveedor con compras y sin NIF
    for c in proveedores:
        if n_compras(c.id) and not normalizar_nif(c.nif):
            avisos.append(Aviso(
                prioridad=BAJA,
                tipo=TIPO_FICHA,
                proveedor=c.nombre or "(sin nombre de proveedor)",
                documentos=f"{n_compras(c.id)} compra(s)",
                fecha=None,
                importe=total_compras(c.id),
                detalle=(
                    f"El proveedor tiene compras registradas pero su ficha tiene «{c.nif.strip()}» como NIF, "
                    "que no es un NIF válido." if (c.nif or "").strip()
                    else "El proveedor tiene compras registradas pero su ficha no tiene NIF."
                ),
                accion="Completar el NIF en la ficha (aparece en sus facturas); es necesario para el modelo 347 y el IVA.",
                ids=(c.id,),
            ))
    return avisos


# ------------------------------------------------ 5. documento mal registrado

def regla_mal_registrados(documentos: Sequence[Documento], params: Parametros = Parametros()) -> list[Aviso]:
    avisos = []
    for doc in _activos(documentos):
        if doc.es_abono:
            continue
        moneda = _moneda(doc)
        if doc.total < CERO:
            avisos.append(Aviso(
                prioridad=MEDIA,
                tipo=TIPO_MAL_REGISTRADO,
                proveedor=doc.proveedor_nombre,
                documentos=doc.referencia,
                fecha=doc.fecha,
                importe=_importe(doc.total, moneda),
                detalle=(
                    f"Compra con total negativo ({importe_moneda(doc.total, moneda)}): "
                    "rectificativa registrada como compra normal." + _nota_moneda(moneda)
                ),
                accion="Registrarla como compra rectificativa (abono de compra) en lugar de compra.",
                ids=(doc.id,),
            ))
        # En el número basta con que aparezca la palabra; en la descripción tiene
        # que ir al principio ("Presupuesto reforma"), porque las facturas suelen
        # citar el presupuesto del que vienen ("según presupuesto nº 45 aceptado").
        palabra = (
            contiene_palabra(doc.numero, params.palabras_presupuesto)
            or empieza_por_palabra(doc.descripcion, params.palabras_presupuesto)
        )
        if palabra:
            avisos.append(Aviso(
                prioridad=ALTA,
                tipo=TIPO_MAL_REGISTRADO,
                proveedor=doc.proveedor_nombre,
                documentos=doc.referencia,
                fecha=doc.fecha,
                importe=_importe(doc.total, moneda),
                detalle=(
                    f'El número o el inicio de la descripción contiene "{palabra}": '
                    "posible presupuesto registrado como compra." + _nota_moneda(moneda)
                ),
                accion="Comprobar si es una factura; si es un presupuesto o proforma, eliminarlo de compras y esperar la factura definitiva.",
                ids=(doc.id,),
            ))
    return avisos


# ------------------------------------------------------------------- todas

def revisar(
    documentos: Sequence[Documento],
    contactos: Sequence[Contacto],
    params: Parametros = Parametros(),
) -> list[Aviso]:
    """Aplica todas las reglas y devuelve los avisos ordenados por prioridad e importe."""
    avisos: list[Aviso] = []
    avisos += regla_duplicados(documentos, params)
    avisos += regla_abono_pendiente(documentos, params)
    avisos += regla_subida_precio(documentos, params)
    avisos += regla_fichas_proveedor(documentos, contactos, params)
    avisos += regla_mal_registrados(documentos, params)
    return ordenar_avisos(avisos)
