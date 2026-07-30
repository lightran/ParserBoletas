# ParserBoletas

Lee boletas/facturas de gastos de viaje (JPG/PNG/PDF), extrae los campos relevantes
con el modelo de visión de Claude, y escribe una fila por boleta en un Excel de
rendición de gastos con el formato de
`plantilla/Form - Chile Expense Report - Peru Travel Junio 2026.xlsx`.

## Índice

- [Configuración del entorno](#configuración-del-entorno)
- [Ejecución](#ejecución)
- [Mecánica de funcionamiento](#mecánica-de-funcionamiento)
- [Esquema del Excel de salida](#esquema-del-excel-de-salida)
- [Reglas de negocio importantes](#reglas-de-negocio-importantes)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Tests](#tests)
- [Fuera de alcance en v1](#fuera-de-alcance-en-v1)

## Configuración del entorno

### Requisitos

- Python 3.9+
- Una API key de Anthropic (variable de entorno `ANTHROPIC_API_KEY`) — **nunca** se
  hardcodea en el código ni en `config.yaml`.

### Instalación estándar (con pip disponible)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Instalación en un entorno sin pip / sin sudo

Si `python3 -m venv` falla porque `ensurepip` no está disponible y no hay acceso a
`sudo` para instalar `python3-venv` o `python3-pip` vía `apt`, se puede bootstrapear
pip manualmente dentro del venv:

```bash
python3 -m venv --without-pip venv
curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py
venv/bin/python3 get-pip.py
venv/bin/pip install -r requirements.txt
```

A partir de ahí, usa `venv/bin/python` y `venv/bin/pip` (o activa el venv con
`source venv/bin/activate`) para todo lo demás.

### Variable de entorno de la API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Sin esta variable, el pipeline no revienta: cada boleta queda marcada automáticamente
para revisión manual con el motivo "ANTHROPIC_API_KEY no está definida" en el reporte
de auditoría.

## Ejecución

```bash
python src/main.py boletas/ --output output/Expense_Report.xlsx --audit output/audit_report.csv
```

### Argumentos

| Argumento | Default | Descripción |
|---|---|---|
| `input_dir` (posicional) | — | Carpeta con las boletas a procesar (jpg/jpeg/png/pdf) |
| `--config` | `config.yaml` | Ruta a un archivo de configuración alternativo |
| `--output` | `output.default_excel_output_path` en config.yaml | Ruta del Excel de rendición generado |
| `--audit` | `output.audit_report_path` en config.yaml | Ruta del reporte de auditoría (CSV) |

### Salida en consola

Al terminar, el comando imprime un resumen y el uso de tokens/costo estimado de la
corrida:

```
Excel de rendición: output/Expense_Report.xlsx
Reporte de auditoría: output/audit_report.csv
Resumen: 9 OK, 3 para revisión, 12 total

── Resumen de ejecución ──
Boletas procesadas:    12
Tokens de entrada:     45,230
Tokens de salida:      3,120
Tokens totales:        48,350
Costo estimado (USD):  $0.1834  (estimado — verificar precios en config.yaml)
```

El costo es siempre una **estimación** — depende de que los precios en
`config.yaml` (`pricing.usd_per_million`) estén al día; los precios de la API
cambian con el tiempo.

### Calibrar el comportamiento sin tocar código

Todos los parámetros de preprocesamiento de imagen, umbrales de confianza, tolerancia
de validación de montos, las listas fijas de monedas/categorías, y los precios por
millón de tokens usados para estimar el costo (`pricing`) viven en `config.yaml`.
Editar ese archivo (o pasar `--config otro.yaml`) para calibrar sin tocar Python.

## Mecánica de funcionamiento

`src/main.py` orquesta un pipeline lineal, archivo por archivo:

```
boletas/*.{jpg,png,pdf}
        │
        ▼
1. preprocess.py   — rasteriza PDFs a imágenes (PyMuPDF) y aplica, según config.yaml:
        │             deskew, denoise, mejora de contraste (CLAHE), upscaling y
        │             binarización opcional.
        ▼
2. extract.py      — envía la(s) imagen(es) ya preprocesadas al modelo de visión de
        │             Claude con un prompt que fija el esquema JSON esperado y las
        │             reglas de negocio (ver más abajo). Devuelve vendor, fecha, hora
        │             de emisión, moneda, monto, tipo de gasto, una confianza por campo,
        │             y el `usage` de tokens de esa llamada (para el resumen de costo).
        ▼
3. currency.py     — parsea el monto extraído respetando el formato numérico
        │             localizado (miles vs. decimales) y normaliza el código de
        │             moneda a uno de los 7 códigos que acepta la plantilla.
        ▼
4. validate.py     — chequeo de consistencia interno (neto + impuesto + propina ≈
        │             total, si el modelo entregó ese desglose), formato de fecha (si
        │             vino), y umbral de confianza. Decide status "OK" o "REVIEW" y
        │             guarda los motivos.
        ▼
5a. excel_writer.py — si se determinó el monto total (esté "OK" o marcada para
        │              revisión): se agrega como fila nueva al Excel de salida (copia
        │              de la plantilla, con las filas de ejemplo limpiadas). FX se
        │              escribe en 1 y Amount in CLP como fórmula "=FX*Amount",
        │              preservando el dropdown de Currency/Expense Type y la fórmula
        │              de la fila de total que trae la plantilla. También estampa la
        │              fecha de ejecución en los dos campos de fecha del encabezado
        │              (Date Submitted y el Date del bloque de firma).
5b. audit_report.csv — TODAS las boletas (OK y REVIEW) quedan registradas acá con:
                        archivo de origen, campos extraídos, confianza y motivo de
                        revisión si aplica. Así se audita cada decisión del pipeline.
```

Una boleta marcada para revisión **sí se escribe** en el Excel con los datos que se
pudieron extraer, siempre que se haya determinado el monto total — la marca de revisión
no desaparece, sigue registrada en `audit_report.csv` y en el resumen de consola, y en
la fila del Excel la columna Comments avisa que hay que mirar la auditoría (ver más
abajo). Si el monto total **no** se pudo determinar, la boleta no se escribe en el
Excel en absoluto — solo queda en el reporte de auditoría, esté OK o no (aunque en la
práctica una boleta sin monto siempre queda para revisión).

### Por qué el camino principal es visión y no OCR clásico

Las boletas de este proyecto varían mucho en calidad (fotos torcidas, térmicas
descoloridas, sombras, distintas monedas e idiomas). Un modelo de visión tolera esa
variedad mucho mejor que Tesseract/OCR clásico, que además no entiende semántica (por
ejemplo, no distinguiría un total de un subtotal, o detectaría que hay dos documentos
en una misma foto). El preprocesamiento de imagen sigue siendo útil para limpiar la
entrada antes de mandarla al modelo, especialmente en fotos de baja calidad.

## Esquema del Excel de salida

Hoja `Expense Report`, encabezado en la fila 8, datos desde la fila 9:

| Columna | Se llena en v1 | Notas |
|---|---|---|
| Item | Sí | Número secuencial 1..N |
| Date | Sí | Fecha de la transacción (no de vencimiento) |
| Amount | Sí | Monto total en la moneda original (sin conversión) |
| Currency | Sí | Uno de: `CLP, USD, BRL, ARG, PEN, COP, EUR` (lista fija de la plantilla) |
| FX | Sí, siempre `1` | v1 no hace conversión de divisas; el usuario ajusta el FX real a mano |
| Amount in CLP | Sí, como fórmula | `=FX*Amount` (ej. `=F9*D9`); se recalcula solo al editar FX a mano |
| Expense Type | Sí | Una de las 22 categorías fijas de la hoja "Cheat Sheet" |
| Comments | Sí | `<nombre de archivo> en la fecha <fecha>`; en filas para revisión, "Boleta para revisión, mirar auditoría" (ver regla de negocio abajo) |

Cada corrida genera el Excel a partir de una copia de la plantilla original (nunca un
archivo desde cero), escribiendo desde la fila 9 hasta la 32 como máximo — ese es el
rango real que cubren los dropdowns de Currency/Expense Type y la fila de total
(`G33 = SUM(G9:G32)`) que trae la plantilla. Si hay más boletas OK que cupo disponible,
el pipeline falla explícitamente en vez de escribir sobre la fila de total.

Además de las filas por boleta, cada corrida estampa la **fecha de ejecución** (la fecha
del sistema al momento de correr el programa, no la fecha de ninguna boleta) en dos
campos de fecha del encabezado/metadata del formulario: **Date Submitted** (celda `D6`)
y el **Date** del bloque de firma "Approved by:" (celda `F39`). Ambos quedan con el mismo
valor. No se toca el formato numérico de esas celdas — cada una conserva el que ya traía
la plantilla (por eso pueden verse distintas entre sí, ej. `27-May-26` en una y
`07-30-26` en la otra).

## Reglas de negocio importantes

**Boleta + voucher de tarjeta en una misma foto**: muchas boletas de Perú incluyen dos
documentos en una sola imagen — la boleta del comercio y el voucher de pago con
tarjeta (izipay, niubiz, transbank). Cuando eso pasa, el monto correcto es el **total
final del voucher de tarjeta (incluye propina)**, no el subtotal de la boleta del
comercio. Ejemplo real: boleta S/295.04 + propina S/29.00 (voucher) = S/324.04, que es
el valor correcto a reportar. Esta regla está codificada en el prompt de `extract.py`.

**Código de moneda "ARG"**: la plantilla usa `ARG` (no el código ISO-4217 `ARS`) para
pesos argentinos. Es una particularidad de esta plantilla específica, no un error. Si el
modelo detecta una moneda que no está en la lista fija de la plantilla, no se agrega
por su cuenta: la boleta queda marcada para revisión manual.

**Formato numérico localizado**: `currency.py` desambigua separador de miles vs.
decimal sin asumir un idioma fijo — si aparecen `.` y `,` juntos, el que aparece último
es el decimal; si aparece un solo tipo de separador, se interpreta como decimal solo
si aparece una vez y el último grupo tiene 1-2 dígitos (ej. `235.40`), y como miles en
el resto de los casos (ej. `464.717` → 464717).

**Formato de Comments**: en filas "OK", `<nombre de archivo> en la fecha <fecha>`, donde
`<nombre de archivo>` es el archivo de origen de la boleta y `<fecha>` usa el mismo
formato que la columna Date (ej. `27-May-26`). Si no se pudo extraer la fecha de la
boleta, Comments queda solo con el nombre de archivo, sin el sufijo — una boleta sin
fecha legible igual puede quedar "OK" y generar su fila. En filas marcadas para
revisión (pero con monto determinado), Comments es siempre el texto fijo "Boleta para
revisión, mirar auditoría", sin importar nombre de archivo ni fecha.

**Boletas para revisión con monto determinado sí se escriben en el Excel**: antes,
cualquier boleta marcada para revisión quedaba excluida del Excel por completo. Ahora,
si se pudo determinar el monto total, la fila se escribe con los datos que sí se
extrajeron (Amount, Currency, FX=1, Amount in CLP) — la única diferencia con una fila
OK es el texto de Comments de arriba. La marca de revisión se sigue registrando igual
que antes en `audit_report.csv` y en el resumen impreso en consola. Si el monto no se
determinó, la boleta sigue sin escribirse (eso no cambió).

## Estructura del proyecto

```
ParserBoletas/
  boletas/            # imágenes/PDFs de boletas a procesar
  plantilla/          # Excel de rendición de ejemplo (formato de referencia)
  src/
    preprocess.py     # deskew, denoise, contraste, upscaling, rasterizado de PDF
    extract.py        # extracción de campos por visión (Claude API)
    currency.py       # parsing de números localizados + normalización de moneda
    validate.py       # consistencia de montos + umbral de confianza
    excel_writer.py   # escritura al formato de la plantilla
    cost.py           # acumulación de tokens + estimación de costo de la corrida
    main.py           # orquesta el pipeline sobre una carpeta
  tests/              # pytest, con casos armados a partir de boletas reales
  config.yaml         # parámetros calibrables
  requirements.txt
  CLAUDE.md           # contexto técnico detallado para seguir iterando con Claude Code
  README.md           # este archivo
```

## Tests

```bash
pytest tests/
```

Cubren el parsing de moneda/números con montos reales de las boletas en `boletas/`, la
regla de consistencia neto+impuesto(+propina)≈total, que una moneda no reconocida nunca
se "invente" (queda marcada para revisión), la escritura del Excel contra la plantilla
real: FX=1 por defecto, Amount in CLP como fórmula, preservación del dropdown de
Currency/Expense Type y de la fórmula de la fila de total, y el estampado de la fecha de
ejecución en Date Submitted (D6) y Date de "Approved by:" (F39) sin alterar el formato
de esas celdas ni la columna Date por fila; el armado de Comments (con fecha, sin
fecha) junto con el caso que confirma que una boleta sin fecha igual queda "OK"; la
acumulación de tokens y el cálculo de costo estimado (suma entre llamadas, fórmula de
costo, formato del resumen), incluyendo un test que corre `main.run()` con la llamada a
la API mockeada y confirma que el resumen se imprime al final con el total acumulado; y
qué filas se escriben en el Excel (`main.py::_build_expense_row`): boleta para revisión
con monto determinado → se escribe con Comments = "Boleta para revisión, mirar
auditoría"; boleta OK → mantiene el formato de nombre de archivo + fecha; boleta para
revisión sin monto → no se escribe (sin cambios); más un test de integración con tres
boletas que confirma que la marca de revisión sigue apareciendo en el resumen de
consola y en `audit_report.csv` aunque la fila ya se haya escrito en el Excel. No hacen
llamadas a la API de Claude (la llamada de red está aislada y mockeada), así que corren
sin necesidad de `ANTHROPIC_API_KEY`.

## Fuera de alcance en v1

- Conversión de divisas real: FX siempre se escribe en `1`, el usuario ajusta el valor real a mano.
- Categorización difusa avanzada más allá de mapear a la lista fija de 23 tipos de gasto.
- Integración con correo/buzón de gastos, interfaz gráfica.
