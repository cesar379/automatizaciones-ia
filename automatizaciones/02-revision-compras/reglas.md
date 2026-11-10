# Reglas · Revisión de compras

La revisión **solo lee** el ERP y **avisa**. No corrige, no borra y no crea nada.

Las reglas son funciones puras en [`revision_compras/reglas.py`](revision_compras/reglas.py). Trabajan sobre un modelo neutro (`Documento`, `Linea`, `Contacto` en [`modelo.py`](revision_compras/modelo.py)) y no dependen de Holded. Para otro ERP basta con escribir un normalizador que lea su API o su archivo exportado y devuelva esos objetos.

## Datos que usan

| Modelo neutro | Holded v2 | Notas |
|---|---|---|
| `Documento.tipo` | recurso leído | `compra` = `/purchases`, `abono` = `/purchase-refunds` |
| `numero` | `document_number` | |
| `fecha` | `date` | Fecha de emisión. Los timestamps Unix de la v1 se pasan a fecha en la `zona_horaria` de la empresa (por defecto Europe/Madrid) |
| `proveedor_id` / `proveedor_nombre` | `contact_id` / `contact_name` | |
| `descripcion` / `notas` | `description` / `notes` | El listado de v2 no trae `notes`: con la v2 no se revisan las notas, y el informe lo indica |
| `moneda` | `currency` | Solo se comparan documentos de la misma moneda |
| `total` | `total` | Holded lo da como cadena decimal |
| `estado` | `status` | Los documentos `cancelled` se ignoran en todas las reglas |
| `Linea.precio`, `unidades`, `descuento_pct` | `lines[].price`, `units`, `discount` | El descuento es un % de línea |
| `Contacto.nif` | `code` (o `vat_number`) | |
| `Contacto.es_proveedor` | `type` ∈ {supplier, creditor} o `supplier_record.num` | |

**Proveedor:** se identifica por su id en el ERP. Si un documento no tiene id, se usa el nombre normalizado. Si no tiene ni id ni nombre, el documento no se compara con ningún otro (duplicados, abonos posteriores, precios).

**Moneda:** solo se comparan documentos de la misma moneda. El importe en juego es en euros: los avisos de documentos en otra moneda tienen importe en juego 0 y el detalle muestra el importe con su moneda.

**Importes de los abonos:** se comparan siempre en valor absoluto. Así da igual que el ERP los guarde en positivo o en negativo.

## Normalización

- **Texto para buscar palabras:** en minúsculas y sin acentos. Cada palabra o frase tiene que aparecer **al inicio de una palabra**: «devolucion» encuentra «Devoluciones», pero «error» no encuentra «terror».
- **Número de documento:** en mayúsculas, sin espacios, guiones, barras, puntos ni ceros a la izquierda en cada bloque de cifras. «F-2026/0007» y «f 2026-7» dan lo mismo. Entre dos bloques de cifras se conserva una marca, para que «01/12» y «11/02» no coincidan. También coinciden el mismo número escrito con y sin separador («F2026-0001» y «F20260001»), si tiene al menos 5 cifras.
- **Números genéricos:** los que no tienen ninguna cifra distinta de cero («S/N», «Ticket», «0») no sirven para detectar duplicados.
- **Nombre:** sin acentos, mayúsculas, puntuación, espacios repetidos ni forma jurídica (S.L., S.A., SLU, S.L.L., S.C.P., C.B., «Sociedad Limitada»…).
- **NIF:** en mayúsculas, sin separadores y sin el prefijo `ES` del NIF-IVA. Los valores de relleno («N/A», «-», «00000000») cuentan como NIF vacío: sin ninguna cifra distinta de cero o con menos de 8 caracteres. No se exige el formato español, para admitir NIF-IVA extranjeros.

## 1. Posible duplicado · prioridad alta

Se comparan documentos **del mismo proveedor, del mismo tipo** (compra con compra, abono con abono) **y de la misma moneda**. Hay posible duplicado si:

- **a)** coincide el número de documento (ver Normalización; los números genéricos no cuentan), o
- **b)** el total coincide (±0,01 €) y las fechas están a **3 días o menos**.

Excepciones (no avisan):

- **Cuotas recurrentes:** el caso (b) no avisa si los dos documentos son de meses distintos y el proveedor factura ese importe en 3 meses distintos o más (alquiler, renting, telefonía).
- **Pedidos fijos:** el caso (b) no avisa si el proveedor factura ese importe en 4 fechas distintas o más, salvo que los dos documentos tengan la misma fecha.
- **Numeración que se reinicia cada año:** el caso (a) no avisa si el mismo número aparece en años distintos con importes distintos, ni con el mismo importe si es una cuota recurrente.

Si tres copias o más se encadenan, salen en un solo aviso. Por importe (caso b) solo se encadenan documentos que caben todos en 3 días: unas entregas cada 2 días no se convierten en un único duplicado de semanas.

**Importe en juego:** la suma de las copias, sin contar la primera.

**Rebaja a prioridad baja:** si hay un abono del mismo proveedor, posterior a la compra y por el mismo importe en valor absoluto. El detalle dice «posiblemente anulada por abono».

## 2. Abono o devolución pendiente · prioridad alta

Aplica a compras con total positivo o cero, no a abonos ni a compras en negativo (esas ya son el abono; la regla 5a avisa si están mal registradas). Avisa si la descripción, las notas o el texto de las líneas contiene alguna de las palabras configuradas en `palabras_abono`. Por defecto: abono, devolver, devolucion, no se hace, anular, anulada, erroneo, error, tienen que hacer.

- Las líneas con precio o unidades negativos no cuentan: la devolución (por ejemplo, «Devolución envases») ya está descontada en la propia factura.
- Las palabras de `palabras_abono_solo_cabecera` (por defecto, «abono») solo se buscan en la descripción y las notas, porque en las líneas suelen ser un producto («Abono orgánico 25 kg», «Abono transporte»).
- Con la API v2 no se descargan las notas (solo vienen en el detalle de cada compra), así que no se revisan. El informe lo indica en una nota.

- Si hay un abono del mismo proveedor, con fecha igual o posterior y **por el mismo importe (±2 %)**, el aviso baja a **prioridad baja** con el texto «comprobar que el abono cubre esta compra».
- Si no lo hay, el aviso es de **prioridad alta** y el importe en juego es el total de la compra. Un abono mayor o menor no cuenta: con datos reales, el abono posterior de un proveedor solía corresponder a otra compra.

## 3. Subida de precio de compra · prioridad media

1. Se agrupan las líneas por proveedor y producto. El producto se identifica por su `sku` y, si no tiene, por el nombre normalizado.
2. **Precio neto unitario** = precio × (1 − descuento de línea %), sin IVA. Si un documento tiene varias líneas del mismo producto, se usa la media ponderada por unidades.
3. Por orden de fecha, cada compra se compara con la **compra anterior** del mismo producto. Hay aviso si el precio sube **igual o más** que `umbral_subida_precio` (por defecto, 5 %).
4. **Importe en juego** = (precio nuevo − precio anterior) × unidades de la compra nueva.

Solo se comparan compras del mismo proveedor y de la misma moneda.

Se ignoran:

- las líneas con precio 0 o negativo, con unidades 0 o negativas, o con precio neto 0 (unidades regaladas con un 100 % de descuento);
- los conceptos de importe variable de `conceptos_precio_variable` (por defecto: porte, transporte, envio, mensajeria, energia, electricidad, consumo, suministro), buscados en el nombre o la descripción de la línea;
- los abonos;
- los productos sin compra anterior;
- las facturas resumidas en una sola línea de 1 unidad, sin referencia de producto (`sku`) y por el importe de toda la factura: es lo habitual cuando un escáner o una persona registra la factura sin copiar sus productos, y su «precio» es el total;
- un mismo nombre con precios distintos dentro de la misma factura y sin `sku`: es un concepto genérico («Servicios», «Factura de…»), no un producto comparable.

Una subida de tarifa compensada con más descuento no avisa, porque se compara el precio neto.

## 4. Ficha de proveedor errónea

Se revisan las fichas de **proveedor**: tipo supplier o creditor, o cualquier ficha con compras. Las fichas de clientes no cuentan.

| Caso | Prioridad | Importe en juego |
|---|---|---|
| a) El NIF de la ficha es el propio de la empresa (`nif_propio`, o `empresa.nif` si está vacío) | Alta | Total de compras de esa ficha |
| b) Dos fichas o más con el mismo NIF normalizado o el mismo nombre normalizado | Media | Compras de las fichas que no son la principal (la principal es la que tiene más compras) |
| c) Proveedor con compras y sin NIF (o con un NIF de relleno) | Baja | Total de compras de esa ficha |

Solo cuentan las compras: los abonos no suman al número de compras ni al importe. El total de compras es la suma neta de las compras en euros.

En el caso (b), el detalle dice cuántas compras tiene cada ficha. Si unas fichas coinciden a la vez por NIF y por nombre, salen en un solo aviso.

## 5. Documento mal registrado

Solo aplica a compras.

| Caso | Prioridad | Detalle |
|---|---|---|
| a) Total negativo | Media | «rectificativa registrada como compra normal» |
| b) El número contiene una de las `palabras_presupuesto` (presupuesto, proforma, oferta), o la descripción **empieza** por una de ellas | Alta | «posible presupuesto registrado como compra» |

En la descripción solo cuenta al principio porque las facturas suelen citar el presupuesto del que vienen («Reforma según presupuesto nº 45 aceptado»).

## Formato de cada aviso

Prioridad, tipo, proveedor, documento(s), fecha, importe en juego (€), detalle y acción sugerida.

Los avisos se ordenan por prioridad (alta, media, baja) y, dentro de cada una, por importe de mayor a menor.

El importe en juego es **orientativo**. Si un documento tiene varios avisos, puede contarse más de una vez.

## Pruebas

Las pruebas están en [`tests/test_reglas.py`](tests/test_reglas.py). Usan solo datos inventados.

**Falsos avisos que no deben saltar:**

- alquiler mensual del mismo importe;
- facturas del mismo importe de proveedores distintos;
- abono legítimo registrado como abono;
- subida de precio compensada con un descuento distinto;
- cuota mensual con numeración que se reinicia cada año;
- tickets sin número («S/N», «Ticket») del mismo proveedor;
- pedidos fijos del mismo importe cada pocos días;
- devolución de envases dentro de la propia factura y «abono» como producto;
- rectificativa registrada como compra con el texto «Abono factura…» (solo avisa la regla 5a);
- portes, energía y otros conceptos de importe variable;
- importes en monedas distintas;
- NIF de relleno («N/A», «00000000»);
- factura que cita el presupuesto aceptado.

**Avisos que sí deben saltar:**

- dos compras del mismo proveedor, fecha e importe con números distintos;
- compra con «se va a devolver» sin abono posterior;
- ficha de proveedor con el NIF propio;
- compra con total negativo;
- «presupuesto» en la descripción.
