# ParserBoletas

Pipeline de línea de comandos que lee boletas/facturas de gastos de viaje (jpg/png/pdf),
extrae los campos relevantes usando el modelo de visión de Claude, y escribe una fila
por boleta en un Excel de rendición de gastos con el formato exacto de
`plantilla/Form - Chile Expense Report - Peru Travel Junio 2026.xlsx`.

## Cómo correrlo

```bash
export ANTHROPIC_API_KEY=sk-...
python src/main.py boletas/ --output output/Expense_Report.xlsx --audit output/audit_report.csv
```

Parámetros por defecto en `config.yaml` (`--config` para usar otro archivo).

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
  previas, mismo campo) se escribe siempre en `1` para cada fila nueva. La v1 no hace
  conversión de divisas ni busca tipos de cambio; el usuario ajusta el FX real a mano
  después, y **Amount in CLP se recalcula solo** porque se escribe como fórmula.
- **Amount in CLP** se escribe como fórmula de Excel `=F{fila}*D{fila}` (FX×Amount), no
  como número fijo, precisamente para que se recalcule al editar FX a mano.
- **Comments**: en filas "OK" se arma como `<nombre de archivo> en la fecha <fecha>`
  (`main.py::build_comments`), donde `<nombre de archivo>` es el archivo de origen de la
  boleta y `<fecha>` usa el mismo formato que la columna Date (`27-May-26`, vía
  `_format_date_like_excel`). Si no se pudo extraer la fecha, Comments queda con solo el
  nombre de archivo (sin sufijo). Por eso `validate.py` **no** exige que la fecha esté
  presente para que una boleta quede "OK" (solo valida el formato si vino) — a
  diferencia de un formato de Comments anterior que sí la exigía. `extract.py` todavía
  extrae un campo `time` (hora de emisión) que quedó de ese formato anterior, pero ya no
  lo usa ni lo valida nada: es inerte. En filas marcadas para revisión pero con monto
  determinado, Comments es el texto fijo `main.py::REVIEW_COMMENTS_TEXT` = "Boleta para
  revisión, mirar auditoría" (ver más abajo).
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
nunca desaparece: `audit_entries`/`audit_report.csv` siguen registrando el `status`
("OK"/"REVIEW") y el motivo de cada boleta, y el resumen impreso en consola sigue
contando "N para revisión" — este comportamiento es independiente de si la fila se
escribió o no en el Excel.

**Límite real de la plantilla**: los dropdowns de Currency/Expense Type y la fila de
total (`G33 = SUM(G9:G32)`) acotan los datos a las filas 9-32 (24 líneas). Si se intenta
escribir más boletas OK que ese cupo, `write_expense_report` lanza `TemplateCapacityError`
en vez de desbordarse silenciosamente sobre la fila de total.

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

- Conversión de divisas real: FX siempre se escribe en `1`, el usuario lo ajusta a mano.
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
(`tests/test_main.py`: con fecha, sin fecha) más el caso de `validate.py` que confirma
que una boleta sin fecha sigue quedando "OK" (`tests/test_validate.py`); y la
acumulación de tokens/costo estimado (`tests/test_cost.py`: suma entre llamadas, fórmula
de costo, formato del resumen) más un test de integración en `tests/test_main.py` que
mockea `extract_receipt` para dos boletas y verifica que el resumen se imprime al final
de `run()` con el total correcto; y `_build_expense_row` (`tests/test_main.py`): boleta
para revisión con monto → se escribe con `REVIEW_COMMENTS_TEXT`, boleta OK → mantiene
Comments de nombre de archivo + fecha, boleta para revisión sin monto → no se escribe
(sin cambios), más un test de integración que corre `run()` con tres boletas mockeando
`process_file` y confirma que la fila de revisión-con-monto queda en el Excel, la de
revisión-sin-monto no, y el resumen impreso y el `audit_report.csv` siguen marcando
ambas como REVIEW. No hacen llamadas a la API de Claude —
`extract.py` aísla la llamada de red en `_call_vision_api` para poder mockearla; la
extracción real por visión no se ha probado en este entorno por falta de
`ANTHROPIC_API_KEY`.
