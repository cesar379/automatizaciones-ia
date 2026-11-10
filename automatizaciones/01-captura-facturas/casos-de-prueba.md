# Casos de prueba

Casos anonimizados de la prueba inicial. Los documentos originales no están en este repositorio.

| Nº | Caso | Resultado esperado |
|---|---|---|
| 1 | Presupuesto en la carpeta de facturas | Clasificar como presupuesto y no registrar |
| 2 | Proveedor solo en el logotipo; sin nombre ni NIF en el texto | Identificarlo por imagen o lista; si no, enviar a revisión |
| 3 | Archivo sin nombre del proveedor, con formato conocido | Marcar el proveedor como deducido y enviar a revisión |
| 4 | Rectificativa con el nombre de archivo "Factura" | Clasificar como rectificativa, con importes negativos |
| 5 | Rectificativa que cita la factura original | Guardar la referencia |
| 6 | Dos tipos de IVA en el mismo documento | Guardar dos desgloses |
| 7 | Retención del 15 % | Restarla del total y enviar a revisión |
| 8 | Dos vencimientos | Guardar ambos; deben sumar el total |
| 9 | Línea idéntica repetida en un albarán | Mantener ambas y avisar |
| 10 | Importe bruto con IVA incluido | Usar la base del cuadro de IVA |
| 11 | Tipo de IVA inusual en combustible | Conservar el dato y avisar |
| 12 | Foto con un ticket encima y pliegues | Leer los datos visibles; marcar pagada si consta |
| 13 | Archivo llamado "Factura de venta" que es una compra | Clasificar por contenido |
| 14 | Otra empresa en el aviso legal | Tomar el proveedor del bloque fiscal |
| 15 | Factura con varios albaranes y destinos | Conservar el destino por línea |
| 16 | Factura sin vencimiento | Dejarlo vacío, sin inventarlo |
| 17 | Ficha de proveedor con el NIF de la empresa receptora | Rechazar el NIF y avisar |
| 18 | Dos fichas para el mismo proveedor | No crear otra y avisar para unificarlas |
| 19 | Presupuesto ya registrado como compra en el ERP | Avisar de la discrepancia |
| 20 | Rectificativa registrada en el ERP como compra normal | Avisar de la discrepancia de tipo |
| 21 | Dos facturas iguales salvo por el número | Avisar de un posible duplicado |
