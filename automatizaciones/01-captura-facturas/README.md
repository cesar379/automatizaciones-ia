# 01 · Captura de facturas de proveedor

**Estado:** `prueba`

Convierte facturas en PDF o imagen en datos revisados, listos para registrarse en el ERP.

## Flujo previsto

Correo o carpeta → clasificar documento → extraer datos → validar → revisión humana → archivo de importación o API del ERP.

## Archivos

- [`esquema-factura.json`](esquema-factura.json): datos que se extraen.
- [`reglas.md`](reglas.md): clasificación y validaciones.
- [`casos-de-prueba.md`](casos-de-prueba.md): casos anonimizados.
- `flujos/`: flujos exportados, sin credenciales.

## Prueba inicial (2026-11-05)

Muestra de 20 documentos variados, elegidos a mano: 19 facturas y 1 presupuesto.

| Dato | Encontrado en las 19 facturas |
|---|---|
| Número, fecha, base, IVA y total | 19 |
| Vencimiento | 17 |
| Nombre y NIF del proveedor en el texto del PDF | 10 |

Los importes cuadran internamente en todas. La lectura se hizo con Claude en una conversación, no con un flujo automático.

### Comparación con el ERP (listado de compras)

| Campo | Coincide |
|---|---|
| Fecha | 16 de 16 |
| IVA | 16 de 16 |
| Total | 16 de 16 |
| Vencimiento | 15 de 15 |

- 3 facturas de 2025 no se pudieron comparar porque no están en el ERP. Una factura sin vencimiento en el documento queda fuera de esa fila.
- El listado no muestra la base ni las líneas, así que esos campos siguen sin comparar.
- La muestra es pequeña y no aleatoria, y el ERP puede contener datos de su propio escáner: esto no es todavía una tasa de aciertos definitiva.
- La lista de proveedores del ERP permite resolver a los proveedores que no aparecen en el texto, siempre que la ficha sea correcta.

## Siguientes pasos

1. Comparar base y líneas con el detalle de cada factura en el ERP.
2. Probar la identificación del proveedor mediante la imagen de la página o una lista de proveedores.
3. Evaluar el escáner del ERP con los mismos casos.
4. Medir el tiempo y el coste por factura.
5. Montar el flujo y usarlo en real entre 2 y 4 semanas.
