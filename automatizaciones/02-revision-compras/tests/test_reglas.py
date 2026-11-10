"""Pruebas de las reglas con datos ficticios: casos que deben avisar y falsos avisos que no."""

from dataclasses import replace
from decimal import Decimal

from revision_compras.modelo import ALTA, BAJA, MEDIA
from revision_compras.reglas import (
    TIPO_ABONO,
    TIPO_DUPLICADO,
    TIPO_FICHA,
    TIPO_MAL_REGISTRADO,
    TIPO_PRECIO,
    Parametros,
    regla_abono_pendiente,
    regla_duplicados,
    regla_fichas_proveedor,
    regla_mal_registrados,
    regla_subida_precio,
    revisar,
)
from tests.fabrica import NIF_PROPIO, abono, compra, contacto, linea

PARAMS = Parametros(nif_propio=NIF_PROPIO)


# ============================================================ 1. Duplicados

class TestDuplicados:
    def test_mismo_proveedor_fecha_e_importe_con_numeros_distintos_avisa(self):
        docs = [
            compra("2026-03-10", "242.00", numero="F-101"),
            compra("2026-03-10", "242.00", numero="F-102"),
        ]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1
        a = avisos[0]
        assert a.tipo == TIPO_DUPLICADO and a.prioridad == ALTA
        assert a.importe == Decimal("242.00")
        assert "F-101" in a.documentos and "F-102" in a.documentos

    def test_mismo_numero_normalizado_avisa_aunque_cambie_importe_y_fecha(self):
        docs = [
            compra("2026-02-01", "100.00", numero="FAC 2026/0007"),
            compra("2026-05-20", "110.00", numero="fac-2026-7"),
        ]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1
        assert "mismo número" in avisos[0].detalle

    def test_importe_a_tres_dias_avisa_y_a_cuatro_no(self):
        assert regla_duplicados([compra("2026-03-01", 50, "A1"), compra("2026-03-04", "50.01", "A2")], PARAMS)
        assert not regla_duplicados([compra("2026-03-01", 50, "A1"), compra("2026-03-05", 50, "A2")], PARAMS)

    def test_alquiler_mensual_de_igual_importe_no_avisa(self):
        docs = [compra(f"2026-{m:02d}-01", "1210.00", numero=f"ALQ-{m}", nombre="Inmobiliaria Ficticia SL")
                for m in range(1, 13)]
        assert regla_duplicados(docs, PARAMS) == []

    def test_cuota_recurrente_a_fin_y_principio_de_mes_no_avisa(self):
        # Facturas de renting de un mes fechadas el 30/31 y la siguiente el 2: 3 días, meses distintos
        docs = [
            compra("2026-01-30", "399.00", "R-01"),
            compra("2026-02-02", "399.00", "R-02"),
            compra("2026-03-02", "399.00", "R-03"),
            compra("2026-04-01", "399.00", "R-04"),
        ]
        assert regla_duplicados(docs, PARAMS) == []

    def test_mismo_importe_de_proveedores_distintos_no_avisa(self):
        docs = [
            compra("2026-03-10", "121.00", "X-1", proveedor="P1", nombre="Proveedor Ejemplo SL"),
            compra("2026-03-10", "121.00", "X-1", proveedor="P2", nombre="Suministros Inventados SA"),
        ]
        assert regla_duplicados(docs, PARAMS) == []

    def test_abono_posterior_por_el_mismo_importe_rebaja_a_baja(self):
        docs = [
            compra("2026-03-10", "242.00", "F-101"),
            compra("2026-03-11", "242.00", "F-102"),
            abono("2026-03-20", "-242.00", "AB-1"),
        ]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1
        assert avisos[0].prioridad == BAJA
        assert "posiblemente anulada por abono" in avisos[0].detalle.lower()

    def test_tres_copias_dan_un_unico_aviso(self):
        docs = [compra("2026-03-10", 80, f"N-{i}") for i in range(3)]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1
        assert avisos[0].importe == Decimal("160")

    def test_numeracion_que_se_reinicia_cada_anio_no_avisa(self):
        docs = [compra("2025-01-15", "100.00", "1"), compra("2026-01-20", "180.00", "1")]
        assert regla_duplicados(docs, PARAMS) == []

    def test_documentos_cancelados_no_cuentan(self):
        docs = [compra("2026-03-10", 90, "C-1"), compra("2026-03-10", 90, "C-2", estado="cancelled")]
        assert regla_duplicados(docs, PARAMS) == []


# ===================================================== 2. Abono pendiente

class TestAbonoPendiente:
    def test_se_va_a_devolver_sin_abono_posterior_avisa_en_alta(self):
        docs = [compra("2026-04-01", "363.00", "F-200", descripcion="Material roto, se va a devolver")]
        avisos = regla_abono_pendiente(docs, PARAMS)
        assert len(avisos) == 1
        assert avisos[0].prioridad == ALTA and avisos[0].tipo == TIPO_ABONO
        assert avisos[0].importe == Decimal("363.00")

    def test_busca_sin_acentos_ni_mayusculas_en_notas_y_lineas(self):
        docs = [
            compra("2026-04-01", 10, "F-1", notas="Pendiente DEVOLUCIÓN parcial"),
            compra("2026-04-02", 20, "F-2", lineas=[linea("Caja errónea, tienen que hacer abono")]),
        ]
        assert len(regla_abono_pendiente(docs, PARAMS)) == 2

    def test_con_abono_posterior_avisa_en_baja(self):
        docs = [
            compra("2026-04-01", "363.00", "F-200", descripcion="Pedido erroneo: anular"),
            abono("2026-04-15", "-363.00", "AB-200"),
        ]
        avisos = regla_abono_pendiente(docs, PARAMS)
        assert len(avisos) == 1 and avisos[0].prioridad == BAJA
        assert "comprobar que el abono cubre esta compra" in avisos[0].detalle.lower()

    def test_abono_anterior_o_de_otro_proveedor_no_cuenta(self):
        docs = [
            abono("2026-03-01", "-50", "AB-OLD"),
            abono("2026-04-10", "-50", "AB-OTRO", proveedor="P2", nombre="Otro Proveedor Ficticio SL"),
            compra("2026-04-01", "50", "F-1", descripcion="hay que devolver"),
        ]
        avisos = regla_abono_pendiente(docs, PARAMS)
        assert len(avisos) == 1 and avisos[0].prioridad == ALTA

    def test_abono_legitimo_registrado_como_abono_no_avisa(self):
        docs = [
            compra("2026-04-01", "121.00", "F-300", descripcion="Compra de material"),
            abono("2026-04-05", "-121.00", "AB-300", descripcion="Abono por devolución de material"),
        ]
        avisos = revisar(docs, [contacto("P1")], PARAMS)
        assert avisos == []

    def test_texto_sin_palabras_clave_no_avisa(self):
        docs = [compra("2026-04-01", 10, "F-1", descripcion="Terror y horrores: libro de terror")]
        assert regla_abono_pendiente(docs, PARAMS) == []

    def test_palabras_configurables(self):
        params = Parametros(palabras_abono=("reclamar",))
        docs = [compra("2026-04-01", 10, "F-1", descripcion="Hay que reclamar"),
                compra("2026-04-01", 10, "F-2", descripcion="Hay que devolver")]
        avisos = regla_abono_pendiente(docs, params)
        assert [a.documentos for a in avisos] == ["F-1"]


# ===================================================== 3. Subida de precio

class TestSubidaPrecio:
    def test_subida_igual_o_mayor_al_umbral_avisa(self):
        docs = [
            compra("2026-01-10", 100, "F-1", lineas=[linea("Tornillo M6", "1.00", "100", sku="TOR-6")]),
            compra("2026-02-10", 106, "F-2", lineas=[linea("Tornillo M6 caja", "1.06", "100", sku="TOR-6")]),
        ]
        avisos = regla_subida_precio(docs, PARAMS)
        assert len(avisos) == 1
        a = avisos[0]
        assert a.tipo == TIPO_PRECIO and a.prioridad == MEDIA
        assert a.importe == Decimal("6.00")
        assert "+6.0 %" in a.detalle and "1,00" in a.detalle and "1,06" in a.detalle

    def test_subida_menor_al_umbral_no_avisa(self):
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Papel A4", "4.00", "10")]),
            compra("2026-02-10", 0, "F-2", lineas=[linea("papel a4", "4.19", "10")]),
        ]
        assert regla_subida_precio(docs, PARAMS) == []

    def test_subida_de_precio_compensada_con_descuento_distinto_no_avisa(self):
        # Precio de tarifa sube de 100 a 110, pero con un 10 % de descuento el neto baja a 99
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Bomba ficticia", "100", "2", descuento="0")]),
            compra("2026-02-10", 0, "F-2", lineas=[linea("Bomba ficticia", "110", "2", descuento="10")]),
        ]
        assert regla_subida_precio(docs, PARAMS) == []

    def test_compara_con_la_compra_anterior_aunque_lleguen_desordenadas(self):
        docs = [
            compra("2026-03-10", 0, "F-3", lineas=[linea("Guante", "2.20", "10")]),
            compra("2026-01-10", 0, "F-1", lineas=[linea("Guante", "2.00", "10")]),
        ]
        avisos = regla_subida_precio(docs, PARAMS)
        assert len(avisos) == 1 and "F-3" in avisos[0].documentos

    def test_ignora_precio_cero_unidades_no_positivas_abonos_y_otros_proveedores(self):
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Pieza", "10", "1")]),
            compra("2026-02-10", 0, "F-2", lineas=[linea("Pieza", "0", "1")]),
            compra("2026-02-11", 0, "F-3", lineas=[linea("Pieza", "20", "-1")]),
            abono("2026-02-12", 0, "AB-1", lineas=[linea("Pieza", "30", "1")]),
            compra("2026-02-13", 0, "F-4", proveedor="P2", nombre="Otro Ficticio SL",
                   lineas=[linea("Pieza", "40", "1")]),
        ]
        assert regla_subida_precio(docs, PARAMS) == []

    def test_umbral_configurable(self):
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Cable", "10", "1")]),
            compra("2026-02-10", 0, "F-2", lineas=[linea("Cable", "10.30", "1")]),
        ]
        assert regla_subida_precio(docs, Parametros(umbral_subida_precio=Decimal("3")))
        assert not regla_subida_precio(docs, PARAMS)


# ================================================= 4. Fichas de proveedor

class TestFichasProveedor:
    def test_ficha_con_el_nif_propio_avisa_en_alta(self):
        contactos = [contacto("P1", "Proveedor Ejemplo SL", nif="ES-B00000099")]
        docs = [compra("2026-01-10", 100, "F-1")]
        avisos = regla_fichas_proveedor(docs, contactos, PARAMS)
        nif = [a for a in avisos if "NIF de la propia empresa" in a.detalle]
        assert len(nif) == 1 and nif[0].prioridad == ALTA and nif[0].tipo == TIPO_FICHA

    def test_fichas_con_mismo_nif_o_mismo_nombre_avisan_en_media(self):
        contactos = [
            contacto("P1", "Proveedor Ejemplo, S.L.", nif="B00000001"),
            contacto("P2", "PROVEEDOR EJEMPLO SL", nif="B00000001"),
            contacto("P3", "Ferretería Inventada S. L. U.", nif="B00000002"),
            contacto("P4", "Ferreteria inventada", nif="B00000003"),
        ]
        docs = [compra("2026-01-10", 100, "F-1", proveedor="P1"),
                compra("2026-01-11", 50, "F-2", proveedor="P1"),
                compra("2026-01-12", 30, "F-3", proveedor="P2")]
        avisos = [a for a in regla_fichas_proveedor(docs, contactos, PARAMS) if a.prioridad == MEDIA]
        assert len(avisos) == 2
        mismo_nif = next(a for a in avisos if "P1" in a.ids)
        assert "el mismo NIF y el mismo nombre" in mismo_nif.detalle
        assert "2 compra(s)" in mismo_nif.detalle and "1 compra(s)" in mismo_nif.detalle
        assert mismo_nif.importe == Decimal("30")

    def test_proveedor_con_compras_sin_nif_avisa_en_baja(self):
        contactos = [contacto("P1", nif=""), contacto("P9", "Sin Compras Ficticio SL", nif="")]
        avisos = regla_fichas_proveedor([compra("2026-01-10", 100, "F-1")], contactos, PARAMS)
        assert len(avisos) == 1 and avisos[0].prioridad == BAJA and avisos[0].ids == ("P1",)

    def test_clientes_con_mismo_nif_no_cuentan(self):
        contactos = [
            contacto("C1", "Cliente Ficticio SL", nif="B00000005", tipo="client"),
            contacto("C2", "Cliente Ficticio SL", nif="B00000005", tipo="client"),
            contacto("P1", nif="B00000001"),
        ]
        assert regla_fichas_proveedor([], contactos, PARAMS) == []

    def test_fichas_correctas_no_avisan(self):
        contactos = [contacto("P1", nif="B00000001"), contacto("P2", "Suministros Inventados SA", nif="A00000002")]
        docs = [compra("2026-01-10", 100, "F-1"), compra("2026-01-10", 100, "F-1", proveedor="P2")]
        assert regla_fichas_proveedor(docs, contactos, PARAMS) == []


# =============================================== 5. Documento mal registrado

class TestMalRegistrados:
    def test_compra_con_total_negativo_avisa_en_media(self):
        avisos = regla_mal_registrados([compra("2026-05-01", "-121.00", "F-9")], PARAMS)
        assert len(avisos) == 1
        assert avisos[0].prioridad == MEDIA and avisos[0].tipo == TIPO_MAL_REGISTRADO
        assert "rectificativa registrada como compra normal" in avisos[0].detalle
        assert avisos[0].importe == Decimal("121.00")

    def test_presupuesto_en_la_descripcion_avisa_en_alta(self):
        avisos = regla_mal_registrados(
            [compra("2026-05-01", "500.00", "F-10", descripcion="Presupuesto reforma oficina")], PARAMS)
        assert len(avisos) == 1 and avisos[0].prioridad == ALTA
        assert "posible presupuesto registrado como compra" in avisos[0].detalle

    def test_proforma_u_oferta_en_el_numero_avisa(self):
        docs = [compra("2026-05-01", 10, "PROFORMA-1"), compra("2026-05-01", 20, "OFERTA 33")]
        assert len(regla_mal_registrados(docs, PARAMS)) == 2

    def test_abono_negativo_y_compra_normal_no_avisan(self):
        docs = [abono("2026-05-01", "-50", "AB-1"), compra("2026-05-01", "50", "F-11", descripcion="Material")]
        assert regla_mal_registrados(docs, PARAMS) == []


# ================================================================ conjunto

def test_revisar_ordena_por_prioridad_e_importe():
    docs = [
        compra("2026-05-01", "-30", "F-1"),                                  # media
        compra("2026-05-02", "900", "F-2", descripcion="presupuesto"),       # alta
        compra("2026-05-03", "100", "F-3", descripcion="hay que devolver"),  # alta
    ]
    avisos = revisar(docs, [contacto("P1")], PARAMS)
    assert [a.prioridad for a in avisos] == [ALTA, ALTA, MEDIA]
    assert avisos[0].importe == Decimal("900")


# ======================================== falsos avisos de la revisión de código

def _moneda(doc, moneda):
    return replace(doc, moneda=moneda)


class TestFalsosAvisosDuplicados:
    def test_cuota_mensual_con_numeracion_que_se_reinicia_cada_anio_no_avisa(self):
        docs = [compra(f"{anio}-{m:02d}-05", "605.00", numero=str(m), nombre="Arrendador Ficticio")
                for anio in (2025, 2026) for m in range(1, 13)]
        assert regla_duplicados(docs, PARAMS) == []

    def test_mismo_numero_e_importe_en_anios_distintos_sin_ser_cuota_si_avisa(self):
        docs = [compra("2025-06-01", "300.00", "7"), compra("2026-06-01", "300.00", "7")]
        assert len(regla_duplicados(docs, PARAMS)) == 1

    def test_tickets_sin_numero_no_se_encadenan(self):
        docs = [
            compra("2026-02-03", "45.10", "S/N", nombre="Gasolinera Ficticia"),
            compra("2026-06-15", "61.30", "S/N", nombre="Gasolinera Ficticia"),
            compra("2026-09-15", "52.00", "s-n", nombre="Gasolinera Ficticia"),
            compra("2026-10-01", "12.00", "Ticket", nombre="Gasolinera Ficticia"),
            compra("2026-10-20", "13.00", "TICKET", nombre="Gasolinera Ficticia"),
            compra("2026-11-01", "14.00", "0", nombre="Gasolinera Ficticia"),
            compra("2026-11-05", "15.00", "0", nombre="Gasolinera Ficticia"),
        ]
        assert regla_duplicados(docs, PARAMS) == []

    def test_tickets_sin_numero_si_avisan_por_importe_y_fecha(self):
        docs = [compra("2026-02-03", "45.10", "S/N"), compra("2026-02-03", "45.10", "S/N")]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1 and "mismo importe" in avisos[0].detalle and "mismo número" not in avisos[0].detalle

    def test_pedido_fijo_cada_dos_dias_no_avisa(self):
        docs = [compra(f"2026-03-{1 + 2 * i:02d}", "45.60", f"P-{i}") for i in range(15)]
        assert regla_duplicados(docs, PARAMS) == []

    def test_pedido_fijo_registrado_dos_veces_el_mismo_dia_si_avisa(self):
        docs = [compra(f"2026-03-{1 + 2 * i:02d}", "45.60", f"P-{i}") for i in range(6)]
        docs.append(compra("2026-03-05", "45.60", "P-2-copia"))
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1 and avisos[0].importe == Decimal("45.60")
        assert "P-2" in avisos[0].documentos and "P-2-copia" in avisos[0].documentos

    def test_no_encadena_por_importe_documentos_a_mas_de_tres_dias(self):
        docs = [compra("2026-03-01", 70, "A1"), compra("2026-03-03", 70, "A2"), compra("2026-03-05", 70, "A3")]
        avisos = regla_duplicados(docs, PARAMS)
        assert avisos
        for a in avisos:
            fechas = sorted(d.fecha for d in docs if d.id in a.ids)
            assert (fechas[-1] - fechas[0]).days <= PARAMS.dias_duplicado
            assert a.importe == Decimal("70")

    def test_mes_y_secuencia_que_coinciden_al_quitar_separadores_no_avisan(self):
        docs = [compra("2026-01-20", "300", "01/12", nombre="Autonomo Ficticio"),
                compra("2026-11-05", "80", "11/02", nombre="Autonomo Ficticio")]
        assert regla_duplicados(docs, PARAMS) == []

    def test_mismo_numero_con_y_sin_separador_avisa(self):
        docs = [compra("2026-03-01", 100, "F2026-0001"), compra("2026-05-01", 100, "F20260001")]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1 and "mismo número" in avisos[0].detalle

    def test_compras_sin_proveedor_no_se_agrupan(self):
        docs = [compra("2026-03-02", "50.00", "A1", proveedor="", nombre=""),
                compra("2026-03-04", "50.00", "Z9", proveedor="", nombre="")]
        assert regla_duplicados(docs, PARAMS) == []

    def test_no_compara_importes_de_monedas_distintas(self):
        docs = [compra("2026-03-10", "100.00", "U-1"), _moneda(compra("2026-03-10", "100.00", "U-2"), "USD")]
        assert regla_duplicados(docs, PARAMS) == []

    def test_duplicado_en_otra_moneda_no_suma_euros_y_lo_dice(self):
        docs = [_moneda(compra("2026-03-10", "100.00", "U-1"), "USD"),
                _moneda(compra("2026-03-10", "100.00", "U-2"), "USD")]
        avisos = regla_duplicados(docs, PARAMS)
        assert len(avisos) == 1 and avisos[0].importe == 0
        assert "USD" in avisos[0].detalle and "€" not in avisos[0].detalle


class TestFalsosAvisosAbono:
    def test_devolucion_de_envases_dentro_de_la_factura_no_avisa(self):
        docs = [compra("2026-04-01", "500.00", "B-1", nombre="Distribuidora Ficticia", lineas=[
            linea("Cerveza barril", "100", "5"), linea("Devolución envases", "-10", "3")])]
        assert regla_abono_pendiente(docs, PARAMS) == []

    def test_devolucion_en_linea_con_unidades_negativas_no_avisa(self):
        docs = [compra("2026-04-01", "470.00", "B-2", lineas=[
            linea("Cerveza barril", "100", "5"), linea("Devolución envases", "10", "-3")])]
        assert regla_abono_pendiente(docs, PARAMS) == []

    def test_rectificativa_registrada_como_compra_no_pide_reclamar_el_abono(self):
        docs = [compra("2026-04-01", "121.00", "F-1"),
                compra("2026-04-10", "-121.00", "R-1", descripcion="Abono factura F-1")]
        avisos = revisar(docs, [contacto("P1")], PARAMS)
        assert [a for a in avisos if a.tipo == TIPO_ABONO] == []
        assert any("rectificativa registrada como compra normal" in a.detalle for a in avisos)

    def test_abono_como_producto_en_las_lineas_no_avisa(self):
        docs = [compra("2026-04-01", "900.00", "V-1", nombre="Vivero Ficticio",
                       lineas=[linea("Abono orgánico 25kg", "18", "50")])]
        assert regla_abono_pendiente(docs, PARAMS) == []

    def test_abono_en_la_descripcion_si_avisa(self):
        docs = [compra("2026-04-01", "90.00", "V-2", descripcion="Pendiente abono por rotura")]
        assert len(regla_abono_pendiente(docs, PARAMS)) == 1

    def test_abono_en_lineas_se_puede_volver_a_buscar(self):
        params = Parametros(palabras_abono_solo_cabecera=())
        docs = [compra("2026-04-01", "900.00", "V-1", lineas=[linea("Abono orgánico 25kg", "18", "50")])]
        assert len(regla_abono_pendiente(docs, params)) == 1

    def test_abono_sin_proveedor_no_cubre_compra_sin_proveedor(self):
        docs = [compra("2026-04-01", "50", "F-1", proveedor="", nombre="", descripcion="hay que devolver"),
                abono("2026-04-10", "-50", "AB-1", proveedor="", nombre="")]
        avisos = regla_abono_pendiente(docs, PARAMS)
        assert len(avisos) == 1 and avisos[0].prioridad == ALTA


class TestFalsosAvisosPrecio:
    def test_portes_y_energia_no_son_subidas_de_precio(self):
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Portes", "12", "1"), linea("Energía consumida", "210", "1")]),
            compra("2026-02-10", 0, "F-2", lineas=[linea("Portes", "18", "1"), linea("Energía consumida", "260", "1")]),
        ]
        assert regla_subida_precio(docs, PARAMS) == []
        assert len(regla_subida_precio(docs, Parametros(conceptos_precio_variable=()))) == 2

    def test_no_compara_precios_en_monedas_distintas(self):
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Caja", "9", "1000", sku="CX")]),
            _moneda(compra("2026-02-10", 0, "F-2", lineas=[linea("Caja", "10", "1000", sku="CX")]), "USD"),
        ]
        assert regla_subida_precio(docs, PARAMS) == []

    def test_subida_en_otra_moneda_muestra_la_moneda_y_no_suma_euros(self):
        docs = [
            _moneda(compra("2026-01-10", 0, "F-1", lineas=[linea("Caja", "9", "1000", sku="CX")]), "USD"),
            _moneda(compra("2026-02-10", 0, "F-2", lineas=[linea("Caja", "10", "1000", sku="CX")]), "USD"),
        ]
        avisos = regla_subida_precio(docs, PARAMS)
        assert len(avisos) == 1 and avisos[0].importe == 0 and "USD" in avisos[0].detalle

    def test_unidades_regaladas_con_descuento_del_100_no_bajan_la_media(self):
        docs = [
            compra("2026-01-10", 0, "F-1", lineas=[linea("Refresco", "1", "10"), linea("Refresco", "1", "2", descuento="100")]),
            compra("2026-02-10", 0, "F-2", lineas=[linea("Refresco", "1", "10")]),
        ]
        assert regla_subida_precio(docs, PARAMS) == []


class TestFalsosAvisosFichas:
    def test_abonos_no_cuentan_como_compras_ni_suman(self):
        contactos = [contacto("P1", "Proveedor Ejemplo SL", nif=NIF_PROPIO)]
        docs = [compra("2026-01-10", "1000", "F-1"), abono("2026-01-20", "-1000", "AB-1")]
        avisos = [a for a in regla_fichas_proveedor(docs, contactos, PARAMS) if a.prioridad == ALTA]
        assert len(avisos) == 1
        assert avisos[0].documentos == "1 compra(s)" and avisos[0].importe == Decimal("1000")

    def test_ficha_con_solo_abonos_y_sin_nif_no_avisa(self):
        contactos = [contacto("P1", nif="")]
        assert regla_fichas_proveedor([abono("2026-01-20", "-50", "AB-1")], contactos, PARAMS) == []

    def test_nif_de_relleno_no_agrupa_fichas_y_cuenta_como_sin_nif(self):
        contactos = [
            contacto("P1", "Fontanero Uno", nif="N/A"),
            contacto("P2", "Pintor Dos", nif="N/A"),
            contacto("P3", "Taller Tres", nif="00000000"),
        ]
        docs = [compra("2026-01-10", 100, "F-1", proveedor="P1", nombre="Fontanero Uno"),
                compra("2026-01-11", 200, "F-2", proveedor="P2", nombre="Pintor Dos"),
                compra("2026-01-12", 300, "F-3", proveedor="P3", nombre="Taller Tres")]
        avisos = regla_fichas_proveedor(docs, contactos, PARAMS)
        assert [a for a in avisos if a.prioridad == MEDIA] == []
        sin_nif = [a for a in avisos if a.prioridad == BAJA]
        assert sorted(a.ids[0] for a in sin_nif) == ["P1", "P2", "P3"]
        assert any("«00000000»" in a.detalle for a in sin_nif)


class TestFalsosAvisosMalRegistrados:
    def test_factura_que_cita_el_presupuesto_aceptado_no_avisa(self):
        docs = [compra("2026-05-01", "12100.00", "F-77", descripcion="Reforma local según presupuesto nº 45 aceptado"),
                compra("2026-05-02", "100.00", "F-78", descripcion="Material s/ oferta 12")]
        assert regla_mal_registrados(docs, PARAMS) == []


class TestCorreccionesDatosReales:
    """Casos vistos al pasar la revisión por una exportación real (reproducidos con datos ficticios)."""

    def test_factura_resumida_en_una_linea_no_es_subida_de_precio(self):
        from dataclasses import replace
        a = replace(compra("2026-06-19", 102.85, "T-1", lineas=[linea("Servicios de telecomunicaciones", "85", "1")]),
                    subtotal=Decimal("85"))
        b = replace(compra("2026-06-25", 253.86, "T-2", lineas=[linea("Servicios de telecomunicaciones", "209.80", "1")]),
                    subtotal=Decimal("209.80"))
        assert regla_subida_precio([a, b]) == []

    def test_producto_de_una_unidad_con_referencia_si_se_compara(self):
        from dataclasses import replace
        a = replace(compra("2026-01-10", 0, "F-1", lineas=[linea("Bomba", "100", "1", sku="BMB-1")]), subtotal=Decimal("100"))
        b = replace(compra("2026-02-10", 0, "F-2", lineas=[linea("Bomba", "120", "1", sku="BMB-1")]), subtotal=Decimal("120"))
        assert len(regla_subida_precio([a, b])) == 1

    def test_mismo_nombre_con_precios_distintos_en_una_factura_se_ignora(self):
        docs = [
            compra("2026-07-01", 0, "H-1", lineas=[linea("Factura de servicios", "3.32", "1"), linea("Factura de servicios", "3.32", "1")]),
            compra("2026-07-05", 0, "H-2", lineas=[linea("Factura de servicios", "59", "1"), linea("Factura de servicios", "25", "1")]),
        ]
        assert regla_subida_precio(docs) == []

    def test_abono_posterior_de_otro_importe_no_rebaja_el_aviso(self):
        docs = [
            compra("2026-06-30", 2169.20, "F-10", descripcion="Lote 5 - se va a devolver"),
            abono("2026-10-31", -16.94, "R-1"),
        ]
        avisos = regla_abono_pendiente(docs)
        assert len(avisos) == 1 and avisos[0].prioridad == ALTA

    def test_abono_posterior_que_cubre_el_importe_rebaja_el_aviso(self):
        docs = [
            compra("2026-06-30", 2169.20, "F-10", descripcion="Lote 5 - se va a devolver"),
            abono("2026-07-15", -2169.20, "R-2"),
        ]
        avisos = regla_abono_pendiente(docs)
        assert len(avisos) == 1 and avisos[0].prioridad == BAJA and "R-2" in avisos[0].detalle

    def test_abono_mayor_de_otra_compra_no_cubre(self):
        docs = [
            compra("2026-06-30", 2169.20, "F-10", descripcion="se va a devolver"),
            compra("2026-08-31", 3406.92, "F-20"),
            abono("2026-10-31", -3406.92, "R-3"),
        ]
        avisos = regla_abono_pendiente(docs)
        assert len(avisos) == 1 and avisos[0].prioridad == ALTA
