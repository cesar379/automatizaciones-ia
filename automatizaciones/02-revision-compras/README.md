# 02 · Revisión de compras

**Estado:** `prueba`

Lee las facturas de compra, los abonos de compra y los proveedores de Holded. Después avisa de lo que conviene revisar antes del cierre o de la declaración de IVA:

- duplicados;
- abonos que faltan;
- subidas de precio;
- fichas de proveedor erróneas;
- documentos mal registrados.

**Solo lee.** No cambia nada en Holded.

## Qué genera

En `resultados/<empresa>/`, sin subirse a GitHub:

- **`revision_compras_AAAA-MM-DD.xlsx`**:
  - Hoja **Resumen**: número de avisos e importe en juego por tipo y por prioridad. Usa fórmulas `COUNTIF`, `COUNTIFS` y `SUMIF` sobre la hoja Avisos, compatibles con Excel 2007 o posterior.
  - Hoja **Avisos**: un aviso por fila, con filtros y la prioridad coloreada (alta en rojo, media en naranja, baja en verde).
- **`revision_compras_AAAA-MM-DD.md`**: resumen breve con los primeros avisos.

Cada aviso incluye:

- prioridad;
- tipo;
- proveedor;
- documento(s);
- fecha;
- importe en juego (€);
- detalle;
- acción sugerida.

Las reglas se explican en [`reglas.md`](reglas.md).

| Tipo de aviso | Prioridad | Ejemplo |
|---|---|---|
| Posible duplicado | Alta (baja si hay un abono que lo anula) | Dos facturas del mismo proveedor, mismo día y mismo importe |
| Abono o devolución pendiente | Alta (baja si ya hay un abono posterior por el mismo importe) | Compra con la descripción «se va a devolver» |
| Subida de precio | Media | El mismo artículo pasa de 1,00 € a 1,06 € netos (+6 %) |
| Ficha de proveedor errónea | Alta, media o baja | Ficha con el NIF de la propia empresa, fichas repetidas o sin NIF |
| Documento mal registrado | Alta o media | Presupuesto registrado como compra, o compra con total negativo |

## 1. Crear la clave de Holded (una sola vez por empresa)

Esto lo hace una persona con acceso a **Desarrolladores** en Holded: rol Developer, o Owner o Admin. Hace falta un plan de pago.

1. En Holded, abre el menú de la cuenta (arriba a la izquierda) > **Configuración** > **Desarrolladores** > **Credenciales**.
2. Pulsa **Agregar API Token**.
3. Marca **solo lectura** en **Compras** (o Contabilidad > Compras) y en **Contactos**. No marques escritura ni otros módulos.
   La API comprueba los permisos `accounting:purchases.read` y `contacts:contacts.read`. Si falta alguno, devuelve el error 403.
4. Pulsa **Crear Token** y copia el valor. **Solo se muestra una vez.**
5. Guárdala **con el nombre de la empresa**, de una de estas formas (`<EMPRESA>` es el nombre de la carpeta `clientes/<empresa>/` en mayúsculas, con `_` en lugar de `-`):
   - en el gestor de contraseñas y, al ejecutar, como variable de entorno: `export HOLDED_API_KEY_<EMPRESA>=...`
   - en un archivo `clientes/<empresa>/.env` con la línea `HOLDED_API_KEY=...`
   - o en el `.env` de la raíz del repositorio (copia `.env.example` a `.env`) con la línea `HOLDED_API_KEY_<EMPRESA>=...`

Los `.env` y las carpetas `clientes/<empresa>/` están en `.gitignore` y nunca se suben.

Cada empresa usa su propia clave para no descargar los datos de una empresa con el nombre de otra. La variable genérica `HOLDED_API_KEY` solo se usa si se pide con `--clave-generica`. Al empezar, el programa dice de dónde ha leído la clave (nunca muestra su valor). No se lee el `.env` de la carpeta desde la que se ejecuta.

> Usa una clave **v2** (API Token). Las claves v1 antiguas no tienen permisos por módulo: dan acceso completo a la cuenta. Solo admiten `api_holded: v1` en la configuración, y no se recomiendan.

Si la clave se filtra, revócala en la misma pantalla y crea otra.

## 2. Configurar la empresa

1. Copia `clientes/_plantilla/` como `clientes/<empresa>/`, por ejemplo `clientes/ejemplo/`. Esa carpeta no se sube a GitHub.
2. Renombra `config.example.yaml` a `config.yaml` **en la copia**, no en `_plantilla/` (por si acaso, `clientes/_plantilla/config.yaml` también está en `.gitignore`).
3. Rellena la sección `revision_compras`:

```yaml
revision_compras:
  nif_propio: "B00000000"        # NIF de la empresa (si se deja vacío se usa empresa.nif)
  umbral_subida_precio: 5        # % de subida del precio neto que genera aviso
  fecha_desde: 2026-01-01        # desde qué fecha revisar (se puede cambiar con --desde)
  api_holded: v2
  zona_horaria: Europe/Madrid    # Atlantic/Canary en Canarias
  palabras_abono: [abono, devolver, devolucion, no se hace, anular, anulada, erroneo, error, tienen que hacer]
  palabras_abono_solo_cabecera: [abono]   # no se buscan en las líneas («abono orgánico» es un producto)
  palabras_presupuesto: [presupuesto, proforma, oferta]
  conceptos_precio_variable: [porte, transporte, envio, mensajeria, energia, electricidad, consumo, suministro]
```

Ajusta las palabras al sector de la empresa: en un vivero «abono» es un producto y en hostelería «devolución de envases» aparece en casi todas las facturas.

Si no hay `fecha_desde` ni `--desde`, se revisa desde el 1 de enero del año anterior.

## 3. Ejecutar

Necesitas Python 3.13 con `openpyxl` y `PyYAML`, y `pytest` para las pruebas. Instálalos con `pip install -r requirements.txt`.

```bash
cd automatizaciones/02-revision-compras
python -m revision_compras --empresa ejemplo                      # descarga y revisa
python -m revision_compras --empresa ejemplo --desde 2026-07-01   # cambia la fecha de inicio
python -m revision_compras --empresa ejemplo --cache              # revisa lo ya descargado, sin llamar a la API
```

- **Descarga:** guarda el JSON tal como llega de Holded en `datos/<empresa>/`, que no se sube a GitHub.
- **`--cache`:** revisa esos archivos sin clave y sin gastar peticiones. Si `--desde` es anterior a la fecha de la descarga, avisa de que faltan compras.
- **`--config RUTA`:** usa otro `config.yaml`.
- **`--clave-generica`:** usa `HOLDED_API_KEY` si la empresa no tiene su propia clave. Úsalo solo si sabes que esa clave es la de esta empresa.
- **Errores:** si falta la clave o la configuración, el programa explica qué hacer y termina con el código 2. Si Holded devuelve un error, termina con el código 1.

### Sin clave: con la exportación de Holded

Si todavía no hay clave de API, se puede revisar el Excel que genera Holded en **Compras > Facturas > Acciones > Exportar líneas**:

```bash
python -m revision_compras --empresa ejemplo --exportacion datos/ejemplo/compras_lineas.xlsx
```

Guarda el archivo en `datos/<empresa>/`, que no se sube a GitHub. No se llama a la API. Esta vía tiene límites, que el informe indica en sus notas:

- la exportación no dice si un documento es compra o abono: se considera abono todo documento con total negativo, así que no se detectan rectificativas registradas como compra normal;
- no incluye notas ni fichas completas de contactos: el NIF sale de la columna «Contact ID» y cada par nombre + NIF cuenta como una ficha;
- si las facturas se registraron resumidas en una línea, apenas hay precios por producto que comparar.

Es también la vía para empresas con otros ERP: basta con un normalizador como [`normalizar_exportacion.py`](revision_compras/normalizar_exportacion.py) para su formato.

**Coste en peticiones.** Una revisión hace unas pocas llamadas:

- compras y abonos: 200 por página;
- contactos: 100 por página.

No se pide el detalle de cada factura. Los planes bajos de Holded tienen un cupo mensual (por ejemplo, 500 peticiones en Starter). Por eso conviene usar `--cache` para repetir la revisión.

## Garantías de solo lectura y de la clave

- **Solo `GET`:** el cliente HTTP ([`holded.py`](revision_compras/holded.py)) solo implementa `GET`. Cualquier otro método (`POST`, `PUT`, `PATCH`, `DELETE`…) lanza `MetodoNoPermitido` antes de tocar la red, tanto en el cliente como en el transporte. Las pruebas lo comprueban.
- **Conexión:** solo HTTPS contra `api.holded.com`. No se siguen redirecciones, así que la clave no puede acabar en otro servidor.
- **La clave no se muestra:** se lee de `HOLDED_API_KEY_<EMPRESA>` (variable de entorno o `.env` de la raíz del repositorio) o de `clientes/<empresa>/.env`; la genérica `HOLDED_API_KEY`, solo con `--clave-generica`. El programa dice de qué origen la ha leído, pero **nunca** imprime su valor ni lo escribe en registros, errores, datos descargados ni informes. Las pruebas lo comprueban con una clave ficticia.
- **Límites de la API:** se deja al menos 1 s entre peticiones (60 por minuto). Ante un error 429 o 5xx se respeta `Retry-After`; si no lo hay, o ante errores de red, se reintenta con espera exponencial.
- **Cupo agotado o Holded caído:** si Holded pide esperar más de 2 minutos (por ejemplo, porque se agotó el cupo mensual), el programa se detiene con un mensaje en lugar de quedarse dormido.
- **Informe seguro:** los textos que vienen de Holded (proveedor, número, detalle) se guardan siempre como texto, aunque empiecen por `=`, y se les quitan los caracteres de control que Excel no admite.
- **Datos reales:** se quedan en `datos/` y `resultados/`. Ninguna de las dos carpetas se sube a GitHub.

## Estructura

| Ruta | Contenido |
|---|---|
| `revision_compras/holded.py` | Cliente de solo lectura de la API de Holded (v2; v1 opcional) |
| `revision_compras/normalizar_holded.py` | JSON de Holded → modelo neutro, tolerante a variantes de nombres de campo |
| `revision_compras/normalizar_exportacion.py` | Excel «Exportar líneas» de Holded → modelo neutro (sin clave de API) |
| `revision_compras/modelo.py` | Modelo neutro: `Documento`, `Linea`, `Contacto`, `Aviso` |
| `revision_compras/texto.py` | Normalización de textos, NIF, números, importes y fechas |
| `revision_compras/reglas.py` | Las 5 reglas: funciones puras, sin dependencia del ERP |
| `revision_compras/informe.py` | Excel y resumen en Markdown |
| `revision_compras/configuracion.py` | `config.yaml` por empresa y lectura de la clave |
| `revision_compras/cli.py`, `__main__.py` | Programa de línea de órdenes |
| `tests/` | Pruebas con datos 100 % ficticios |

## Pruebas

```bash
cd automatizaciones/02-revision-compras
python -m pytest -q
```

## Otros ERP

Las reglas solo usan el modelo neutro. Para revisar compras de otro ERP, o de un Excel o CSV exportado, basta con escribir un normalizador equivalente a `normalizar_holded.py` o `normalizar_exportacion.py` y llamar a `reglas.revisar(documentos, contactos, parametros)`.

## Primera prueba con datos reales

En la primera empresa piloto, con la exportación de 200 compras y abonos de 2026, la revisión dio 17 avisos (7 de prioridad alta). Entre ellos:

- una ficha de proveedor con el NIF de la propia empresa;
- un posible duplicado del mismo importe y fecha;
- un presupuesto registrado como compra;
- cuatro compras cuyo texto anuncia un abono o devolución sin abono posterior que las cubra;
- fichas repetidas y proveedores sin NIF.

La prueba sacó a la luz falsos avisos que ya están corregidos: líneas resumen comparadas como precios, abonos de otras compras dados por buenos y el pie del informe de Holded leído como documento.

## Pendiente de verificar con datos reales


- Si los abonos llegan en `/purchase-refunds` con importes positivos o negativos. Las reglas usan el valor absoluto, así que funcionan en ambos casos.
- El tamaño de página real y el límite de peticiones del plan, leyendo las cabeceras `X-RateLimit-*`.
- Si el listado de compras incluye las líneas completas. Según la documentación, sí.
- Las notas (`notes`) solo vienen en el detalle de cada compra (`GET /api/v2/purchases/{id}`), que no se descarga para no gastar cupo. Con la v2, la regla 2 busca solo en la descripción y en las líneas; el informe lo indica en una nota.
- Las compras en otra moneda (`currency` distinta de EUR) se comparan solo entre sí y no suman al importe en juego en euros: el tipo de cambio (`currency_change`) solo viene en el detalle.
