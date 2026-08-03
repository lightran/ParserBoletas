# ParserBoletas

Pipeline que lee boletas/facturas de gastos de viaje (jpg/png/pdf), extrae los campos
relevantes usando el modelo de visión de Claude, y escribe una fila por boleta en un
Excel de rendición de gastos con el formato exacto de
`plantilla/Form - Chile Expense Report - Peru Travel Junio 2026.xlsx`. Dos interfaces
sobre el mismo pipeline de negocio: una CLI (`src/main.py`, interactiva por consola) y
una interfaz web local (`app.py` + `src/web/`, ver sección "Interfaz web" más abajo) —
ninguna reescribe extracción/columnas/auditoría/cálculos, son capas de interfaz.

## Cómo correrlo (CLI)

```bash
python src/main.py boletas/ --output output/Expense_Report.xlsx --audit output/auditoria.xlsx
```

No hace falta exportar `ANTHROPIC_API_KEY` a mano: si no está seteada, el programa la
pide por consola la primera vez y la guarda en `secrets.yaml` (ver sección "API key de
Anthropic" abajo). Parámetros por defecto en `config.yaml` (`--config` para usar otro
archivo).

**Es interactiva**: después de leer todas las boletas, pide por consola el FX de cada
moneda no-CLP y una descripción del reporte (ver sección de FX arriba y "Nombre del
archivo de salida" más abajo) — no hay modo no interactivo/batch todavía. La interfaz
web (`python app.py`) pide los mismos datos, pero como campos de formulario en vez de
prompts de consola — ver "Interfaz web" abajo.

### Nombre del archivo de salida

El nombre que se pasa en `--output` (o el default de `config.yaml`) **siempre se
reemplaza** por `Expense_Report_<descripción saneada>.xlsx`, en el mismo directorio —
`main.py::run()` hace `output_path.with_name(...)` después de pedir la descripción, así
que el directorio de `--output` se respeta pero el nombre de archivo no.
`sanitize_filename_component()` reemplaza los caracteres prohibidos (`/ \ : * ? " < > |`)
y los espacios (internos o de los extremos) por `_`, colapsando repeticiones — un solo
criterio consistente para ambos casos.

## API key de Anthropic (`src/api_key.py`)

`api_key.resolve_api_key(secrets_path)` resuelve la API key con esta prioridad, y deja
`ANTHROPIC_API_KEY` seteada en el proceso para que `extract.py` la lea **sin ningún
cambio** (sigue haciendo `os.environ.get("ANTHROPIC_API_KEY")` tal cual):

1. La variable de entorno `ANTHROPIC_API_KEY`, si ya está definida (prioridad — permite
   seguir usando el flujo anterior, ej. en CI).
2. `secrets.yaml` (ruta configurable con `--secrets`, default `secrets.yaml` en el cwd),
   si tiene un token guardado bajo la clave `anthropic_api_key`.
3. La pide por consola vía `getpass.getpass()` (no hace eco en pantalla), reintentando
   si queda vacía, y la guarda en `secrets.yaml` para la próxima corrida.

Se llama una sola vez, en `main()`, **antes** de `run()` — `run()` y todo lo demás del
pipeline quedan sin tocar. **`secrets.yaml` es un archivo separado de `config.yaml`** (no
se mezcla con parámetros/precios) y está en `.gitignore`. Guarda la key en **texto
plano** (única forma simple de persistirla localmente) — el archivo lleva un comentario
de advertencia explícito, y se intenta `os.chmod(path, 0o600)` best-effort (en un
`try/except OSError`, porque en Windows los bits POSIX no aplican igual y no debe
romper la corrida).

Para la interfaz web (que no puede usar `getpass`, no tiene consola), se agregaron dos
funciones **aditivas** que delegan en las mismas privadas de siempre — no cambian el
comportamiento de `resolve_api_key`:

- `has_saved_key(secrets_path)`: `True` si ya hay key utilizable (env var o archivo),
  sin pedirla ni bloquear — usado para decidir si mostrar el campo de token en la
  página.
- `save_api_key(token, secrets_path)`: guarda `token` con el mismo criterio de
  persistencia (texto plano, chmod 600 best-effort) y lo deja seteado en el proceso.
  Levanta `ValueError` si `token` es blanco.

## Interfaz web (`app.py`, `src/web/`)

Capa de interfaz alternativa a la CLI — mismo pipeline, sin reescribir extracción,
columnas, auditoría ni cálculos. Arquitectura, según lo acordado con el usuario antes
de implementar:

- **Monolito, un solo proceso**: `python app.py` levanta FastAPI + uvicorn sirviendo la
  página y corriendo el pipeline en el mismo proceso (sin microservicios, sin frontend
  Node/React separado). `app.py` abre el navegador solo (`webbrowser.open`, vía
  `threading.Timer`, biblioteca estándar — funciona igual en Windows/Linux) apuntando a
  `http://127.0.0.1:8000` (host/puerto configurables con `PARSERBOLETAS_HOST` /
  `PARSERBOLETAS_PORT`). La CLI (`src/main.py`) sigue funcionando sin cambios.
- **UI**: página única `src/web/templates/index.html`, Tailwind vía CDN + Alpine.js vía
  CDN (sin build de Node) para la reactividad (mostrar/ocultar campos, habilitar el
  botón). Estilo sidebar oscura + cards inspirado en un dashboard Hitachi de
  referencia, con el rojo Hitachi (`#8C1D40`, definido en `templates/index.html` vía
  `tailwind.config`) como único color de acento.
- **Reuso de lógica**: `src/web/routes.py` es una fachada delgada sobre las mismas
  funciones que usa la CLI — `main.process_all` (extracción + validación por boleta),
  `main.detect_fx_requirements` (qué monedas necesitan qué dato de FX),
  `complementary_info.CurrencyConversion`/`compute_real_fx`, `excel_writer.
  write_expense_report`, `audit_writer.write_audit_report`, `cost.format_summary`. No
  hay una segunda implementación de ninguna de estas reglas.
- **`main.py` se partió en piezas reusables** (sin cambiar el comportamiento de `run()`,
  cubierto por los mismos tests de siempre):
  - `main.process_all(files, config, on_progress=None) -> ProcessingSummary`: el loop
    de `process_file` + armado de filas + orden, que antes vivía inline en `run()`.
    `run()` (CLI) y `POST /api/jobs/{id}/parse` (web) llaman a la misma función.
  - `main.detect_fx_requirements(rows) -> FxRequirements`: la detección de qué monedas
    presentes necesitan FX (extraída de `determine_fx`, que la sigue usando
    internamente). La web la usa para decidir qué campos de FX mostrar, sin pasar por
    `input()`.
  - `main.compute_missing_requirements(...) -> List[str]`: función pura (sin I/O) con
    la regla de habilitación del botón "Crear rendición" — boletas cargadas, parseo
    hecho, descripción saneable no vacía, FX de USD si hace falta, selección completa
    por cada moneda que necesita el cálculo de FX real. La usan tanto
    `POST /api/jobs/{id}/validate` (el botón consulta esto en cada cambio relevante del
    formulario) como `POST /api/jobs/{id}/generate` (rechaza con 400 si falta algo) —
    la regla vive una sola vez, en Python, testeada sin levantar el servidor.
- **Estado por sesión (`src/web/state.py::JobStore`)**: como el flujo web está partido
  en varias llamadas HTTP (subir → parsear → generar) en vez de una corrida bloqueante
  de consola, cada "job" (uuid4, sin autenticación — herramienta local de un solo
  usuario) guarda en memoria del proceso las boletas subidas (en un directorio temporal
  propio) y los resultados intermedios (`ProcessingSummary`, `FxRequirements`, rutas de
  los Excel generados). No hay persistencia entre reinicios del proceso ni entre
  procesos — se borra al apagar el servidor (`JobStore.close()` en el `lifespan` de
  FastAPI).
- **Flujo por etapas** (dependencia real: las monedas y candidatos para el FX real solo
  se conocen después de parsear):
  1. `POST /api/jobs` crea la sesión.
  2. `POST /api/jobs/{id}/receipts` (multipart) sube boletas; rechaza extensiones fuera
     de `main.SUPPORTED_SUFFIXES`.
  3. `POST /api/jobs/{id}/parse` corre `process_all` + `detect_fx_requirements`;
     devuelve monedas detectadas, candidatos por moneda (para el selector de boleta de
     conversión) y el uso de tokens acumulado hasta ahí.
  4. `POST /api/jobs/{id}/validate` (llamado por el JS en cada cambio relevante del
     formulario) devuelve si ya se puede generar.
  5. `POST /api/jobs/{id}/generate` arma `fx_rates`/`conversions` a partir de lo
     enviado (mismo `CurrencyConversion` que la CLI, sin pasar por consola), llama a
     `excel_writer.write_expense_report`/`audit_writer.write_audit_report`, y devuelve
     las URLs de descarga (`GET /api/jobs/{id}/download/{report|audit}`) más el mismo
     resumen de costo que imprime la CLI (`cost.format_summary`, texto idéntico).
- **Token en contexto web**: `GET /api/config-status` chequea `api_key.has_saved_key`
  para que la página decida si mostrar el campo password; `POST /api/config/api-key`
  llama a `api_key.save_api_key` (mismo criterio de persistencia que la CLI, ver
  sección anterior).

## Compatibilidad con Windows

Revisado a fondo — la mayor parte del pipeline ya era compatible sin cambios: todo el
manejo de archivos ya usaba `pathlib.Path` (nada de rutas POSIX hardcodeadas), no hay
`subprocess`/comandos de shell en ningún lado, la rasterización de PDF ya usa
PyMuPDF/`fitz` (no `pdf2image`/poppler), y Tesseract no se usa en ningún lado — el único
camino de extracción es visión por Claude. Lo único que hacía falta:

- **`main.py::_ensure_utf8_console()`**: reconfigura `sys.stdout`/`sys.stderr` a UTF-8
  al arrancar (`stream.reconfigure(encoding="utf-8")`, en un `try/except` tolerante a
  streams que no exponen ese método). Sin esto, los `print()` con tildes, `──` o `$`
  (sobre todo `cost.format_summary`) pueden lanzar `UnicodeEncodeError` en una consola
  Windows con code page legacy tipo cp1252. Se llama al inicio de `main()`, antes de
  cualquier otra cosa.
- Todo `open()` de texto que escribe el pipeline (el `secrets.yaml` nuevo incluido) usa
  `encoding="utf-8"` explícito.

## Setup del entorno

Este entorno no tiene `pip` instalado a nivel de sistema y no hay acceso a `sudo`
(`ensurepip` falla, `apt install python3-venv` requiere root). El venv se creó así:

```bash
python3 -m venv --without-pip venv
venv/bin/python3 get-pip.py   # bootstrap de pip dentro del venv
venv/bin/pip install -r requirements.txt
```

## Esquema del Excel de rendición (hoja "Expense Report")

Encabezado en fila 8, datos desde la fila 9: `Item | Date | Amount | Currency | FX |
Amount in CLP | Expense Type | Comments`.

- **FX** (el tipo de cambio a CLP — a veces referido como "columna FIX" en conversaciones
  previas, mismo campo): CLP siempre queda en `1` (nunca se pregunta). `main.py::run()`
  determina el FX de cada moneda no-CLP presente vía `main.py::determine_fx` **una vez
  por moneda** (no por boleta), después de leer todas las boletas y antes de escribir el
  Excel — ver la sección "FX real de moneda extranjera" más abajo para el detalle
  completo. En resumen: USD se pregunta directo por consola; el resto de las monedas usa
  un FX **real**, calculado en dos pasos a partir de una boleta elegida por el usuario y
  el USD que le cobró el banco en la tarjeta (documentado en la pestaña "Complementary
  info" del Excel de salida). El valor resultante se carga en `row.fx` de todas las filas
  de esa moneda antes de llamar a `excel_writer.write_expense_report`. Filas con moneda
  no determinada (`None`) quedan en `DEFAULT_FX`=1 (no hay moneda contra la cual pedir
  FX). **Amount in CLP se recalcula solo** porque se escribe como fórmula.
- **Amount in CLP** se escribe como fórmula de Excel `=F{fila}*D{fila}` (FX×Amount), no
  como número fijo, precisamente para que se recalcule al editar FX a mano.
- **Comments**: en filas "OK" es el nombre del archivo de origen de la boleta, **sin su
  extensión** (`main.py::build_comments`, vía `Path(...).stem` — remueve solo la última
  extensión, así que `boleta.lima.01.jpg` → `boleta.lima.01`). No incluye la fecha.
  `validate.py` **no** exige que la fecha esté presente para que una boleta quede "OK"
  (solo valida el formato si vino) — regla independiente del formato de Comments, que
  sigue vigente porque una boleta sin fecha legible igual debe poder quedar "OK".
  `extract.py` todavía extrae un campo `time` (hora de emisión) que quedó de un formato
  de Comments anterior, pero ya no lo usa ni lo valida nada: es inerte. En filas
  marcadas para revisión pero con monto determinado, Comments es el mismo nombre sin
  extensión más el sufijo `main.py::REVIEW_COMMENTS_SUFFIX` = " (Marcada para Revision)"
  (`main.py::build_review_comments`) — ej. `boleta_taxi_01 (Marcada para Revision)` — para
  que al confirmar los datos baste con borrar el sufijo en vez de escribir el
  nombre/descripción desde cero.
- **Currency** usa la lista fija de la hoja "Cheat Sheet" del Excel: `CLP, USD, BRL,
  ARG, PEN, COP, EUR`. Nota: la plantilla usa **"ARG"**, no el código ISO-4217 "ARS",
  para pesos argentinos — es una particularidad de esta plantilla, no un error de
  `currency.py`. Si el modelo detecta una moneda fuera de esta lista, `normalize_currency_code`
  devuelve `None` y la boleta queda marcada para revisión — nunca se inventa un código nuevo.
- **Expense Type** usa la lista fija de 22 categorías de la hoja "Cheat Sheet".

**Campos de fecha del encabezado** (no confundir con la columna Date por fila, `COL_DATE`):
cada corrida estampa la fecha de ejecución del programa (`date.today()`) en dos celdas
del encabezado/metadata: `DATE_SUBMITTED_CELL` = **D6** (etiqueta "Date Submitted:" en
B6) y `APPROVAL_DATE_CELL` = **F39** (etiqueta "Date   :" en E39, dentro del bloque de
firma "Approved by:" que empieza en E37). No se toca el `number_format` de ninguna de
las dos celdas — cada una conserva el que ya traía la plantilla, y **son distintos entre
sí**: D6 usa `[$-409]d\-mmm\-yy;@` (se ve `27-May-26`) y F39 usa `mm-dd-yy` (se ve
`07-30-26`), aunque el valor de fecha subyacente sea el mismo.

Cada corrida genera un Excel a partir de una copia de la plantilla (`openpyxl.load_workbook`,
nunca un archivo desde cero) desde la fila `first_data_row` (9) hasta `last_data_row`
(32, configurable en `config.yaml`). **Qué filas se escriben** (`main.py::_build_expense_row`):
se escribe cualquier boleta —OK o marcada para revisión— en la que se haya podido
determinar el monto total (`result.amount is not None`); si no se determinó el monto, no
se escribe ninguna fila, esté OK o no (ese caso no cambió). La marca de revisión en sí
nunca desaparece: toda boleta con `not validation.ok` va a `review_cases` y por lo tanto
a una pestaña en `auditoria.xlsx` (ver sección siguiente), y el resumen impreso en
consola sigue contando "N para revisión" — esto es independiente de si la fila llegó a
escribirse en el Excel de rendición.

**Límite real de la plantilla**: los dropdowns de Currency/Expense Type y la fila de
total (`G33 = SUM(G9:G32)`) acotan los datos a las filas 9-32 (24 líneas). Si se intenta
escribir más boletas OK que ese cupo, `write_expense_report` lanza `TemplateCapacityError`
en vez de desbordarse silenciosamente sobre la fila de total.

## Reporte de auditoría (auditoria.xlsx)

`audit_writer.py::write_audit_report(review_cases, config, output_path)` genera el
reporte de auditoría como `.xlsx`, **no** CSV (formato anterior, eliminado). Solo
contiene boletas con `not validation.ok` — las boletas OK no aparecen acá, ya quedaron
reflejadas en su fila del Excel de rendición. Una pestaña por caso (motivo de revisión +
Amount/Currency/Date/nombre de archivo + la imagen **original** de la boleta embebida,
nunca la versión preprocesada — se carga con `preprocess.load_pages()`, que no aplica
deskew/denoise/CLAHE, a diferencia de `preprocess.preprocess_file()` que sí; para PDF
rasteriza la primera página), más una pestaña "Índice" al principio con hipervínculos a
cada caso. Nombres de pestaña saneados/truncados a 31 caracteres y deduplicados vía
`sanitize_sheet_name()` — si dos archivos truncan al mismo nombre, se agrega un sufijo
numérico. El nombre completo del archivo siempre queda dentro de la pestaña aunque el
título esté truncado. **Si no hubo casos para revisión, no se genera el archivo** (y si
existe uno de una corrida anterior en esa ruta, se borra, para que su ausencia siga
siendo una señal confiable). La imagen se reescala a un ancho máximo de
`audit_writer.MAX_IMAGE_WIDTH_PX` (700px) antes de embeberse, para no inflar el archivo.

## Uso de tokens y costo estimado

Cada llamada a `_call_vision_api` en `extract.py` captura `response.usage` (input,
output, cache_creation_input_tokens, cache_read_input_tokens) y lo adjunta al
`ExtractionResult.usage` (dict crudo). `main.py::run()` acumula esto en un
`cost.TokenUsage` a lo largo de toda la corrida (una llamada por boleta hoy; si en
el futuro se agregan reintentos, ya quedarían contados automáticamente porque se
acumula por respuesta real de la API, no por boleta) y al final imprime un resumen
(`cost.format_summary`) con tokens y costo estimado en USD. Los precios viven en
`config.yaml` → `pricing.usd_per_million` (input/output/cache_write/cache_read),
**nunca hardcodeados** — cambian con el tiempo, hay que verificarlos contra
platform.claude.com/docs/en/pricing. El costo es siempre "estimado": depende
enteramente de que esos precios estén al día. Si una boleta falla antes de recibir
respuesta de la API (ej. sin `ANTHROPIC_API_KEY`), su `usage` queda vacío y no suma
nada al costo — no se factura lo que no se llegó a pedir.

## Regla de negocio no obvia: boleta + voucher de tarjeta

Boletas fotografiadas en Perú suelen incluir **dos documentos en una sola imagen**: la
boleta/factura del comercio y el voucher de pago con tarjeta (izipay, niubiz,
transbank). Confirmado contra la plantilla de ejemplo ya resuelta:

| Boleta comercio | + Propina (voucher) | = Monto que quedó en la rendición |
|---|---|---|
| S/295.04 (Dinner StorageData) | S/29.00 | S/324.04 |
| S/214.00 (Lunch America Movil) | S/21.40 | S/235.40 |
| S/330.00 (Dinner BCP) | S/33.00 | S/363.00 |
| S/203.20 (Lunch Jun 12) | S/20.30 | S/223.50 |

**Regla: si hay un voucher de tarjeta en la imagen, `amount` = total final del voucher
(incluye propina), no el subtotal/total de la boleta del comercio.** Esto está
codificado en el prompt de `extract.py` (`used_card_voucher_total`). Si se ve que el
modelo falla en detectar esto, revisar/ajustar ese prompt antes que tocar `currency.py`
o `validate.py`.

## FX real de moneda extranjera (pestaña "Complementary info")

`src/complementary_info.py` calcula, con regla de 3 en dos pasos, el FX real de cada
moneda extranjera (distinta de CLP y de USD) a partir del monto en USD que el banco
cobró en la tarjeta por esa compra — reemplaza el ingreso manual de FX para esas
monedas. Ejemplo real (boleta en soles peruanos):

- Dato A = monto de la boleta en moneda origen (223.50 PEN, elegido por el usuario
  entre las boletas de esa moneda).
- Dato B = USD que el banco cobró por ese movimiento en la tarjeta (67.41 USD,
  ingresado por el usuario).
- Dato C = tipo de cambio USD → CLP del banco (922 — ver más abajo de dónde sale).
- Paso 1: `FX(origen→USD) = Dato B / Dato A` = 0.301611.
- Paso 2: `FX(origen→CLP) = FX(origen→USD) × Dato C` = 278.09 ≈ 278 — este es el valor
  que se carga en `row.fx` para todas las filas de esa moneda.

**USD es un caso especial**: si hay boletas en USD, su FX se sigue preguntando directo
por consola (no tiene sentido aplicarle la regla de 3 a sí misma) — y ese mismo valor
se reutiliza como Dato C para las demás monedas. Si el reporte no tiene ninguna boleta
en USD pero sí otras monedas extranjeras, Dato C se pregunta aparte, **una sola vez**,
y se reutiliza para todas (`main.py::determine_fx`).

**Flujo interactivo** (`main.py::prompt_receipt_selection`/`prompt_usd_charged`, una
vez por moneda extranjera no-USD presente, después de leer todas las boletas): se
muestra una lista indexada de las boletas de esa moneda (archivo + monto + fecha), el
usuario elige el índice a usar como Dato A, y después ingresa el Dato B (USD cobrado,
valida positivo con `main._parse_positive_fx`, reintenta si no).

**Escritura en el Excel**: la plantilla ya trae, en la pestaña "Complementary info",
un ejemplo de referencia con las dos tablas de este cálculo (celdas `P23:R31` — ver
constantes `CELL_DATO_A`/`CELL_DATO_B`/`CELL_DATO_C`/`CELL_STEP1_COPY` en
`complementary_info.py`) y 3 imágenes: la boleta+voucher (zona derecha, la única que
se reemplaza, por la boleta seleccionada — cargada con `audit_writer.
load_original_image_for_embedding`, la imagen ORIGINAL sin preprocesar, mismo criterio
que el reporte de auditoría) y dos screenshots del banco (listado de movimientos y
tipo de cambio — la app **nunca** las toca, las actualiza el usuario a mano),
conectadas a las tablas con flechas azules. Hay **una pestaña clonada por moneda
extranjera** (título `"Complementary info - <MONEDA>"`, ej. "Complementary info -
PEN"), insertada justo después de "Expense Report". **Si no hay ninguna moneda que
necesite este cálculo** (reporte solo con CLP, o CLP+USD), la pestaña "Complementary
info" de la plantilla se elimina del Excel de salida — no aplica.

**Decimales coherentes con "Expense Report"**: la plantilla trae `R30` (resultado
final del Paso 2, el mismo número que termina en `row.fx`) con `number_format = "0"`
(sin decimales), mientras que la columna FX de "Expense Report" usa formato contable
con 2 decimales — mismo valor, dos hojas, dos cantidades de decimales distintas.
`apply_conversions()` recibe `fx_number_format` (leído en `excel_writer.py` desde
`ws.cell(first_row, COL_FX).number_format`, la celda real de la plantilla, no
hardcodeado) y se lo aplica a `R30` en cada pestaña clonada, para que el número se
vea igual en las dos hojas.

**Dos límites de openpyxl obligaron a un manejo especial** (mismo espíritu que el
`<extLst>` de los dropdowns, ver "Trampas de openpyxl" abajo):

- `Workbook.copy_worksheet()` **no copia imágenes ni dibujos** — por eso
  `apply_conversions()` clona la hoja con `copy_worksheet` (preserva valores, fórmulas,
  merges, anchos de columna — todo correctamente remapeado contra el `styles.xml` real
  del workbook en memoria) y **reinserta las 3 imágenes a mano**, con las mismas
  coordenadas de ancla (`TwoCellAnchor`/`AnchorMarker`) que trae la plantilla.
- **openpyxl descarta los conectores de flecha (`<xdr:cxnSp>`) al guardar cualquier
  hoja con dibujos** — no los modela, así que se pierden en cualquier `wb.save()`,
  toquen o no la hoja. Se reinyectan como XML crudo después de guardar
  (`reinject_arrows()`), extrayendo los bloques `<xdr:twoCellAnchor>` con `cxnSp` de la
  plantilla ORIGINAL (nunca de la copia ya guardada, para no arrastrar el problema de
  índices de estilo) y declarando `xmlns:xdr` directamente en el bloque inyectado
  (mismo truco que el `xr:uid` del `<extLst>`, para no depender de que el `<wsDr>` raíz
  que regenera openpyxl declare ese prefijo).

**No intentar clonar la hoja copiando el XML crudo de la plantilla** (`sheet2.xml`)
directamente en el archivo de salida: `openpyxl` **reconstruye `styles.xml` al
guardar** (probado: no es un passthrough, cambia de tamaño y de orden de índices), así
que los `s="..."` de celda de la plantilla original ya no apuntan a los estilos
correctos en el archivo de salida. Por eso `apply_conversions()` clona la hoja
mientras el workbook todavía está en memoria (vía `copy_worksheet`, antes de
`wb.save()`), no después.

Verificado end-to-end (valores, imágenes y flechas) abriendo el archivo generado con
LibreOffice headless, con una y con dos monedas extranjeras simultáneas (cada una en
su propia pestaña, sin pisarse).

## Formato numérico localizado

`currency.py` implementa desambiguación de separador de miles/decimal agnóstica al
idioma: si aparecen '.' y ',' juntos, el que aparece último es el decimal; si solo
aparece un tipo de separador, se interpreta como decimal solo si aparece una vez y el
último grupo tiene 1-2 dígitos (ej. `235.40`), y como miles en el resto de los casos
(ej. `464.717` → 464717, boleta de avión en CLP sin decimales). Ver
`tests/test_currency.py` para los casos reales que fijan este comportamiento.

## Trampas de openpyxl

- `worksheet.cell(row, column, value=None)` es un **no-op** cuando `value=None` —
  openpyxl lo interpreta como "no cambiar el valor", no como "limpiar la celda"
  (ver código fuente de `Worksheet.cell`). Para limpiar o escribir un valor que puede
  ser `None`, hay que asignar `.value` directamente sobre el objeto Cell
  (`ws.cell(row, col).value = None`), que es lo que hace `_set_cell()` en
  `excel_writer.py`. Si se agrega código nuevo que escribe celdas, usar esa función en
  vez de `ws.cell(..., value=...)` directamente.
- **openpyxl descarta el `<extLst>` de la hoja al guardar** (no soporta la extensión
  `x14:dataValidation` que Excel usa para los dropdowns de Currency/Expense Type — de
  ahí el warning "Data Validation extension is not supported"). `write_expense_report`
  reinyecta ese bloque XML manualmente después de `wb.save()` (`_extract_ext_lst` /
  `_restore_ext_lst`), resolviendo la ruta real del sheetN.xml vía `workbook.xml` +
  `workbook.xml.rels` (no asumir que "Expense Report" siempre es `sheet1.xml`: el
  nombre de archivo interno puede cambiar). Los atributos `xr:uid` del bloque original
  dependen de un `xmlns:xr` declarado en la raíz `<worksheet>` de la plantilla, que
  openpyxl tampoco reescribe — hay que quitarlos (son solo tracking de revisión de
  Excel, no afectan el dropdown) o el XML queda inválido ("unbound prefix"). Verificado
  end-to-end abriendo el archivo generado con LibreOffice headless: el dropdown
  sobrevive y las fórmulas (`G9=F9*D9`, `G33=SUM(G9:G32)`) se recalculan bien.
- **openpyxl también descarta los conectores de flecha (`<xdr:cxnSp>`) de cualquier
  hoja con dibujos al guardar**, y `Workbook.copy_worksheet()` no copia imágenes ni
  dibujos — ver la sección "FX real de moneda extranjera" arriba
  (`complementary_info.py`) para el detalle completo de cómo se resuelve (clonar antes
  de guardar + reinyectar flechas después, igual patrón que el `<extLst>` de arriba).

## Fuera de alcance en v1 (a propósito)

- Conversión de divisas automática vía API de tipo de cambio externa: el FX real se
  calcula (regla de 3) a partir de datos que ingresa el usuario (monto de boleta
  elegida + USD cobrado por el banco), no se consulta un servicio de FX.
- Modo no interactivo/batch: tanto la CLI (`determine_fx`/`prompt_report_description`,
  siempre usan `input()`) como la interfaz web (siempre pide estos datos por
  formulario) requieren que alguien complete estos pasos en cada corrida.
- Categorización difusa avanzada más allá de mapear a la lista fija de 22 tipos.
- Integración con correo/buzón de gastos.
- Multi-usuario o despliegue remoto de la interfaz web: `JobStore` guarda el estado de
  cada sesión en memoria del proceso, sin autenticación — pensada para un solo usuario
  corriendo `app.py` en su propia máquina.

## Tests

`pytest tests/` — cubren parsing de moneda/números con los montos reales de las 12
boletas en `boletas/`, la regla de consistencia neto+impuesto(+propina)≈total (incluida
la regla del voucher de tarjeta), que una moneda no reconocida nunca se "inventa" (queda
`None` y fuerza revisión), la escritura del Excel contra la plantilla real: FX=1 por
defecto (sin heredar residuos como el 255 de filas vacías), Amount in CLP como fórmula,
preservación de la fórmula de la fila de total y de los dropdowns de Currency/Expense
Type, el error `TemplateCapacityError` al exceder el cupo de filas, y el estampado de la
fecha de ejecución en D6/F39 (mismo valor en ambas, cada una con su propio number_format
preservado, sin afectar la columna Date por fila); el armado de Comments
(`tests/test_main.py`: nombre de archivo sin extensión, remueve solo la última
extensión con nombres de varios puntos) más el caso de `validate.py` que confirma
que una boleta sin fecha sigue quedando "OK" (`tests/test_validate.py`); y la
acumulación de tokens/costo estimado (`tests/test_cost.py`: suma entre llamadas, fórmula
de costo, formato del resumen) más un test de integración en `tests/test_main.py` que
mockea `extract_receipt` para dos boletas y verifica que el resumen se imprime al final
de `run()` con el total correcto; y `_build_expense_row` (`tests/test_main.py`): boleta
para revisión con monto → se escribe con `build_review_comments` (nombre sin extensión +
`REVIEW_COMMENTS_SUFFIX`), boleta OK → mantiene Comments de nombre de archivo sin
extensión, boleta para revisión sin monto → no se escribe
(sin cambios), más un test de integración que corre `run()` con tres boletas mockeando
`process_file` y confirma que la fila de revisión-con-monto queda en el Excel, la de
revisión-sin-monto no, y que `auditoria.xlsx` tiene pestaña para ambas boletas REVIEW
(no para la OK); y `audit_writer.py` (`tests/test_audit_writer.py`, usando boletas
reales — una jpeg y un PDF de `boletas/` — para probar el camino real de embebido de
imagen incluyendo el rasterizado de PDF): saneo/truncado/deduplicado de nombres de
pestaña, pestaña por caso con el motivo y los valores extraídos, imagen efectivamente
embebida (verificado inspeccionando `xl/media/` dentro del .xlsx generado, no solo la
API de openpyxl), hipervínculos del índice a cada pestaña, y que no se genera archivo
(y se borra uno preexistente) cuando no hay casos para revisión; y el paso interactivo
de FX/nombre de archivo (`tests/test_main.py`, mockeando `builtins.input` con
`_mock_inputs()`): `sanitize_filename_component` (caracteres prohibidos, espacios
internos/de los extremos, colapso de guiones bajos repetidos), `prompt_report_description`
(reintenta si sanea a vacío), `prompt_fx_for_currency` (acepta punto o coma decimal,
reintenta ante negativos/cero/no-numéricos), `prompt_receipt_selection` (devuelve la
boleta en el índice elegido, reintenta ante índice fuera de rango o no numérico),
`prompt_usd_charged` (mismo criterio de validación que `prompt_fx_for_currency`), y
`determine_fx` (vacío si solo hay CLP o moneda `None` sin preguntar nada; USD se
pregunta directo sin pasar por selección de boleta; una moneda no-USD con USD presente
reutiliza el FX de USD como Dato C; sin boleta en USD se pregunta Dato C aparte; dos
monedas no-USD reutilizan el mismo Dato C sin volver a preguntarlo), y un test de
integración de `run()` que confirma que el FX ingresado queda cargado en las filas de
esa moneda mientras CLP queda en 1 y Amount in CLP sigue siendo fórmula. Los tests de
integración existentes de `run()` también tuvieron que empezar a mockear
`builtins.input` (antes no lo necesitaban) porque ahora `run()` siempre pide la
descripción del reporte; y `complementary_info.py` (`tests/test_complementary_info.py`,
usando una boleta real de `boletas/` y la plantilla real, vía
`excel_writer.write_expense_report(..., conversions=...)`): `compute_real_fx` contra el
ejemplo de referencia (223.50 PEN / 67.41 USD / TC 922 → 278.09), que sin conversiones
la pestaña "Complementary info" se elimina, que con una conversión se crea
"Complementary info - <MONEDA>" justo después de "Expense Report" con las celdas
`P24`/`Q24`/`Q30`/`P31` correctas y las fórmulas de la plantilla (`R24`, `R30`) intactas,
que la imagen embebida es la boleta seleccionada (3 imágenes en la pestaña, no la de
ejemplo de la plantilla), que las flechas conectoras sobreviven la reinyección (`cxnSp`
presente en el XML del drawing final), y que dos monedas extranjeras simultáneas crean
dos pestañas independientes sin pisarse. `src/api_key.py`
(`tests/test_api_key.py`, mockeando `getpass.getpass`): prioridad de la variable de
entorno sobre el archivo, que no pregunta si el archivo ya tiene token válido, que
pregunta y guarda cuando no hay nada, reintento ante input vacío, token en blanco en el
archivo se trata como ausente, el archivo queda en UTF-8 con la advertencia de texto
plano, y manejo con `pathlib.Path` incluyendo creación de directorios anidados. Y
`main._ensure_utf8_console` (`tests/test_main.py`): reconfigura stdout/stderr, tolera
streams sin `reconfigure()`, y un test que reproduce el `UnicodeEncodeError` real contra
un stream `cp1252` y confirma que la reconfiguración lo evita. No hacen llamadas a la
API de Claude — `extract.py` aísla la llamada de red en `_call_vision_api` para poder
mockearla; la extracción real por visión no se ha probado en este entorno por falta de
`ANTHROPIC_API_KEY`.

Los helpers nuevos que comparten la CLI y la interfaz web tienen su propia cobertura
pura en `tests/test_main.py` (sin FastAPI): `process_all` arma el mismo
`ProcessingSummary` que antes armaba `run()` inline (filas ordenadas, casos para
revisión, uso acumulado), `detect_fx_requirements` detecta USD/monedas de conversión
igual que hacía `determine_fx` antes de pedir nada por consola, y
`compute_missing_requirements` cubre cada requisito de la regla de habilitación del
botón "Crear rendición" (sin boletas, sin parsear, descripción vacía/no saneable, falta
FX de USD, monedas de conversión pendientes) de forma aislada. `api_key.has_saved_key`/
`save_api_key` (`tests/test_api_key.py`, sin `getpass`) cubren el reemplazo del flujo de
consola para la web: detecta key por env var o archivo sin pedirla, guarda y setea el
proceso, rechaza token en blanco. Y `tests/test_web.py`
(`fastapi.testclient.TestClient`, con `main.process_file` mockeado igual que en
`test_main.py`, sin pegarle a la API de Claude): sirve la página, sube boletas y
rechaza extensiones no soportadas, permite quitar una boleta antes de parsear,
`/parse` detecta monedas y arma los candidatos por moneda para el selector de
conversión, `/validate` refleja la misma regla de `compute_missing_requirements` antes
y después de completar los campos, `/generate` rechaza con 400 si falta algo y si no
genera los archivos descargables correctos — incluyendo que la pestaña "Complementary
info" se elimine con solo CLP y se cree "Complementary info - PEN" con el FX real
correcto cuando hay una conversión, y que una boleta para revisión deje
`auditoria.xlsx` disponible para descargar.
