# Automatizaciones administrativas con IA

> Marco para diseñar, probar y empaquetar como servicio automatizaciones con IA de tareas administrativas (empezando por la **captura automática de facturas**). Se validan primero en empresas propias y después se replican en clientes.

![IA](https://img.shields.io/badge/IA_aplicada-procesos_administrativos-D97757)
![Make / Zapier](https://img.shields.io/badge/Make_·_Zapier-integraciones-6D00CC)
![Estado](https://img.shields.io/badge/estado-en_desarrollo-yellow)

### Lo más destacado

- **Metodología replicable:** cada automatización tiene objetivo, reglas, esquema de datos, casos de prueba y métricas.
- **Una base común + configuración por empresa**, sin reglas de cliente dentro de los flujos.
- **Revisión humana** en todo lo que mueve dinero o sale hacia terceros.
- **Privacidad por diseño:** política explícita de qué datos pueden y no pueden subirse.
- Catálogo, hoja de ruta y registro de decisiones documentados.

---

## Guía técnica · Automatizaciones de administración

Serie de automatizaciones con IA para tareas administrativas comunes. Se prueban primero en empresas propias y se empaquetan después como servicio replicable.

## Principios

- **Una base común y una configuración por empresa.** Las reglas de cada empresa no se escriben dentro de los flujos.
- **Se conecta con los programas de cada empresa.** Prioridad: API, Zapier o Make, archivos y, como último recurso, RPA.
- **Revisión humana** en todo lo que mueva dinero o salga hacia terceros, al menos al principio.
- **Sin datos reales en este repositorio.** Consulta [privacidad](docs/privacidad.md).

## Estructura

| Ruta | Contenido |
|---|---|
| [`docs/catalogo.md`](docs/catalogo.md) | Lista de automatizaciones y estado de cada una |
| [`docs/hoja-de-ruta.md`](docs/hoja-de-ruta.md) | Fases y condiciones para vender |
| [`docs/decisiones.md`](docs/decisiones.md) | Decisiones tomadas y sus motivos |
| [`docs/privacidad.md`](docs/privacidad.md) | Qué puede y qué no puede subirse |
| [`automatizaciones/`](automatizaciones/) | Una carpeta numerada por automatización |
| [`clientes/_plantilla/`](clientes/_plantilla/) | Plantilla de configuración por empresa |

## Añadir una automatización

Crea `automatizaciones/NN-nombre/` con:

- `README.md`: objetivo, entradas, salidas, estado y métricas.
- `reglas.md`: comportamiento y validaciones.
- `casos-de-prueba.md`: casos anonimizados.
- `flujos/`: flujos exportados, sin credenciales.

Después actualiza el [catálogo](docs/catalogo.md).

## Estado actual

En marcha: [01 · Captura de facturas de proveedor](automatizaciones/01-captura-facturas/).
