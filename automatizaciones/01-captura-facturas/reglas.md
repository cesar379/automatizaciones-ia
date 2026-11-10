# Reglas

## Clasificación

- Determinar el tipo por el contenido, nunca por el nombre del archivo.
- Los presupuestos y albaranes no se registran como facturas.
- Una rectificativa conserva el signo negativo y, si se indica, la factura original.

## Extracción

- El NIF del proveedor no es el de la empresa receptora.
- Tomar el proveedor del bloque fiscal, no de los avisos legales del pie.
- Tomar la base del cuadro de IVA: el "importe bruto" puede incluir IVA.
- Guardar un desglose por cada tipo de IVA y todos los vencimientos.
- Indicar de dónde sale el proveedor; si se deduce, enviarlo a revisión.

## Validaciones

- Suma de bases + suma de cuotas − retención = total (tolerancia: 0,01 €).
- Suma de líneas = suma de bases, considerando las líneas con IVA incluido.
- Suma de vencimientos = total, con tolerancia de redondeo.
- Cuota = base × tipo de IVA, con tolerancia de redondeo.

## Enviar a revisión

- Falta el proveedor o su NIF, o fue deducido.
- Falla alguna validación.
- Hay líneas idénticas en el mismo albarán.
- El tipo de IVA no es el habitual para ese producto.
- Lleva retención.
- Los datos del proveedor no coinciden con su ficha.
- Número y proveedor coinciden con una factura ya registrada.
- Proveedor, fechas, descripción e importe coinciden con otra factura, aunque cambie el número.
- El NIF del proveedor es el de la propia empresa.
- Existe más de una ficha para el mismo proveedor.
