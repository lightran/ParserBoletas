# ParserBoletas

Pipeline de línea de comandos que lee boletas/facturas de gastos de viaje (jpg/png/pdf),
extrae los campos relevantes usando el modelo de visión de Claude, y escribe una fila
por boleta en un Excel de rendición de gastos con el formato exacto de
`plantilla/Form - Chile Expense Report - Peru Travel Junio 2026.xlsx`.

## Cómo correrlo

```bash
python src/main.py boletas/ --output output/Expense_Report.xlsx --audit output/auditoria.xlsx
```

No hace falta exportar `ANTHROPIC_API_KEY` a mano: si no está seteada, el programa la
pide por consola la primera vez y la guarda en `secrets.yaml` (ver sección "API key de
Anthropic" abajo). Parámetros por defecto en `config.yaml` (`--config` para usar otro
archivo).

**Es interactivo**: después de leer todas las boletas, pide por consola el FX de cada
moneda no-CLP y una descripción del reporte (ver sección de FX arriba y "Nombre del
archivo de salida" más abajo) — no hay modo no interactivo/batch todavía.

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
  previas, mismo campo): CLP siempre queda en `1` (nunca se pregunta). Para cada moneda
  distinta a CLP presente en el reporte, `main.py::run()` pregunta el FX por consola
  **una vez por moneda** (no por boleta) después de leer todas las boletas y antes de
  escribir el Excel — ver `main.py::prompt_fx_rates`/`_parse_positive_fx` (reutiliza
  `currency.parse_localized_amount` para aceptar `922`, `922.50` o `922,50`; solo acepta
  positivos, si no vuelve a preguntar). El valor se carga en `row.fx` de todas las filas
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

## Fuera de alcance en v1 (a propósito)

- Conversión de divisas automática/API de tipo de cambio: el FX se pide al usuario por
  consola (una vez por moneda), no se busca solo. No hay forma no interactiva de
  correr el pipeline todavía (`prompt_fx_rates`/`prompt_report_description` siempre
  usan `input()`).
- Categorización difusa avanzada más allá de mapear a la lista fija de 22 tipos.
- Integración con correo/buzón de gastos, UI.

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
(reintenta si sanea a vacío), `prompt_fx_rates` (pregunta solo por monedas no-CLP
presentes, nunca por CLP ni por moneda `None`, acepta punto o coma decimal, reintenta
ante negativos/cero/no-numéricos), y un test de integración de `run()` que confirma que
el FX ingresado queda cargado en las filas de esa moneda mientras CLP queda en 1 y
Amount in CLP sigue siendo fórmula. Los tests de integración existentes de `run()`
también tuvieron que empezar a mockear `builtins.input` (antes no lo necesitaban) porque
ahora `run()` siempre pide la descripción del reporte. `src/api_key.py`
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
