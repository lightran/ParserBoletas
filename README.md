# ParserBoletas

Lee boletas/facturas de gastos de viaje (JPG/PNG/PDF), extrae los campos relevantes
con el modelo de visión de Claude, y escribe una fila por boleta en un Excel de
rendición de gastos con el formato de
`plantilla/Form - Chile Expense Report - Peru Travel Junio 2026.xlsx`.

## Índice

- [Configuración del entorno](#configuración-del-entorno)
- [Ejecución](#ejecución)
- [Interfaz web](#interfaz-web)
- [Mecánica de funcionamiento](#mecánica-de-funcionamiento)
- [Esquema del Excel de salida](#esquema-del-excel-de-salida)
- [Reporte de auditoría](#reporte-de-auditoría)
- [Reglas de negocio importantes](#reglas-de-negocio-importantes)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Tests](#tests)
- [Fuera de alcance en v1](#fuera-de-alcance-en-v1)

## Configuración del entorno

### Requisitos

- Python 3.9+
- Una API key de Anthropic — **nunca** se hardcodea en el código. Se resuelve en este
  orden (ver "API key de Anthropic" abajo): variable de entorno `ANTHROPIC_API_KEY` si
  ya está definida, si no el archivo local `secrets.yaml`, si no la pide por consola y
  la guarda ahí.
- **Windows**: funciona igual con Python 3.9+ desde [python.org](https://www.python.org/downloads/windows/)
  (marcar "Add python.exe to PATH" en el instalador) o desde Microsoft Store. No hace
  falta instalar nada más (sin poppler, sin Tesseract — ver "Compatibilidad con
  Windows" abajo).

### Instalación estándar (Linux/macOS, con pip disponible)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Instalación en Windows

```powershell
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Todas las dependencias en `requirements.txt` tienen wheels precompilados para Windows
en PyPI (`opencv-python-headless`, `pymupdf`, `pillow`, etc.) — no requieren compilador
ni instalar nada por fuera de `pip`.

### Instalación en un entorno sin pip / sin sudo (Linux)

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

### API key de Anthropic

No hace falta configurar nada de antemano. La primera vez que corres el pipeline sin
`ANTHROPIC_API_KEY` seteada, te la pide por consola (sin mostrarla en pantalla, vía
`getpass`) y la guarda en `secrets.yaml` (en el directorio desde donde corres el
comando, o la ruta que pases con `--secrets`) para que no te la vuelva a pedir. Ese
archivo:

- **Es distinto de `config.yaml`** — solo guarda el token, nada de parámetros.
- **Ya está en `.gitignore`**, nunca se sube al repo.
- Guarda la key en **texto plano** (es la única forma simple de persistirla
  localmente) — no lo compartas ni lo pegues en tickets o chats.

Si preferís seguir usando la variable de entorno (por ejemplo en CI), definila antes de
correr el comando y tiene prioridad sobre el archivo:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # Linux/macOS
$env:ANTHROPIC_API_KEY = "sk-ant-..."      # Windows PowerShell
```

Si el token termina siendo inválido o falta, cada boleta queda marcada automáticamente
para revisión manual con el motivo correspondiente en el reporte de auditoría — el
pipeline no revienta.

### Compatibilidad con Windows

El resto del pipeline ya funcionaba en Windows sin cambios: todo el manejo de archivos
usa `pathlib.Path` (nada de rutas `/home/...` hardcodeadas), no hay comandos de shell
propios de Unix, y la rasterización de PDF usa PyMuPDF (`fitz`), que se instala solo
con `pip` — a diferencia de `pdf2image`, no necesita instalar poppler aparte. **No se
usa Tesseract en ningún lado** — el único camino de extracción es visión por Claude, así
que no hay ningún binario externo que instalar. Lo único que hacía falta era forzar
UTF-8 en la consola (los mensajes en español usan tildes, `──` y `$`, que pueden fallar
con `UnicodeEncodeError` en una consola Windows con code page legacy tipo cp1252) — el
programa lo hace solo al arrancar, no requiere ninguna configuración de tu parte.

## Ejecución

```bash
python src/main.py boletas/ --output output/Expense_Report.xlsx --audit output/auditoria.xlsx
```

Mismo comando en Windows (PowerShell o cmd), una vez activado el venv — no hace falta
`python3`, con `python` alcanza porque el venv ya apunta al intérprete correcto.

### Argumentos

| Argumento | Default | Descripción |
|---|---|---|
| `input_dir` (posicional) | — | Carpeta con las boletas a procesar (jpg/jpeg/png/pdf) |
| `--config` | `config.yaml` | Ruta a un archivo de configuración alternativo |
| `--output` | `output.default_excel_output_path` en config.yaml | Ruta del Excel de rendición generado |
| `--audit` | `output.audit_report_path` en config.yaml | Ruta del reporte de auditoría (.xlsx) |
| `--secrets` | `secrets.yaml` | Archivo local donde se guarda/lee la API key de Anthropic |

### Es interactivo

Después de leer todas las boletas y antes de escribir el Excel final, el programa pide
por consola:

1. **El FX de cada moneda distinta a CLP** presente en el reporte (CLP no se pregunta —
   queda siempre en `1`):
   - **USD**: se pregunta directo, un tipo de cambio USD → CLP (acepta punto o coma
     decimal, ej. `922` o `922,50`; si el valor no es válido, vuelve a preguntar).
   - **Cualquier otra moneda** (PEN, BRL, etc.): se calcula un **FX real**, con regla de
     3 en dos pasos, a partir de la boleta que elijas y el USD que tu banco te cobró en
     la tarjeta por esa compra — ver "FX real de moneda extranjera" más abajo. Este
     cálculo queda documentado en la pestaña "Complementary info" del Excel de salida.
2. **Una descripción del reporte**, para nombrar el archivo de salida.

No hay modo no interactivo/batch todavía — correr el pipeline siempre requiere
responder estas preguntas.

### FX real de moneda extranjera

Para cada moneda extranjera que no sea USD (ej. PEN, BRL), en vez de pedirte el tipo de
cambio directamente, el programa te ayuda a calcularlo con el mismo criterio que exige
el formulario ("usa el mismo tipo de cambio presentado en la cartola/bill de la
tarjeta"):

1. Te muestra una lista numerada de las boletas en esa moneda (archivo, monto, fecha) y
   eliges cuál usar como referencia — normalmente la boleta cuyo movimiento ya ves
   reflejado en tu cartola de tarjeta.
2. Te pide el monto en USD que el banco cobró por esa compra en la tarjeta.
3. Si ya ingresaste un tipo de cambio USD → CLP (porque también tenías boletas en USD),
   lo reutiliza; si no, te lo pide aparte una sola vez (se reutiliza para todas las
   monedas que lo necesiten).

Con esos tres datos calcula, en dos pasos: `moneda origen → USD` (USD cobrado / monto de
la boleta) y luego `→ CLP` (multiplicando por el tipo de cambio USD → CLP). Ese
resultado es el FX que se usa en el reporte para esa moneda — **y queda documentado**,
paso a paso, en una pestaña `Complementary info - <MONEDA>` del Excel de salida (una por
cada moneda extranjera), junto con la foto de la boleta elegida, **con la misma
cantidad de decimales que la columna FX de "Expense Report"** (2 decimales), para que
el mismo número se vea igual en las dos hojas. Si tu banco cobra el movimiento en
tarjeta directamente en la moneda de origen o el proceso no aplica a tu caso, podés
editar el FX a mano en el Excel después — la columna Amount in CLP se recalcula sola.

Si el reporte no tiene ninguna moneda que necesite este cálculo (todo CLP, o CLP+USD),
la pestaña "Complementary info" no aparece en el Excel de salida.

### Nombre del archivo de salida

El archivo de rendición **siempre** queda nombrado `Expense_Report_<descripción
saneada>.xlsx`, en el mismo directorio que apunte `--output` (o el default de
`config.yaml`) — el nombre de archivo que traiga `--output` se reemplaza, el
directorio no. La descripción se sanea: los caracteres prohibidos en un nombre de
archivo (`/ \ : * ? " < > |`) y los espacios (internos o de los extremos) se
reemplazan por `_`, colapsando repeticiones — un solo criterio consistente para
ambos casos.

### Salida en consola

Al terminar, el comando imprime un resumen y el uso de tokens/costo estimado de la
corrida:

```
Excel de rendición: output/Expense_Report.xlsx
Reporte de auditoría: output/auditoria.xlsx
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

## Interfaz web

Alternativa a la CLI: la misma lógica de negocio (extracción, columnas, auditoría,
cálculo de FX, resumen de costos — nada de eso cambia), pero interactuando por una
página local en el navegador en vez de por consola.

```bash
python app.py
```

Un solo comando, un solo proceso (FastAPI + uvicorn sirviendo la página y corriendo
el pipeline, sin frontend separado ni build de Node): levanta el servidor en
`http://127.0.0.1:8000` y abre el navegador ahí automáticamente. `Ctrl+C` para
detenerlo. Puertos/host configurables con las variables de entorno
`PARSERBOLETAS_PORT` / `PARSERBOLETAS_HOST` si el 8000 ya está en uso. Correr desde la
raíz del repo, igual que la CLI (las rutas de `config.yaml` son relativas al directorio
de trabajo).

Flujo en la página:

1. **API key de Anthropic**: si no hay una guardada (ni en `secrets.yaml` ni en
   `ANTHROPIC_API_KEY`), la página pide un campo tipo password y la guarda con el mismo
   criterio que la CLI (texto plano en `secrets.yaml`, gitignoreado).
2. **Cargar boletas**: arrastrar y soltar (o elegir archivos) jpg/png/pdf. Se puede
   quitar un archivo de la lista antes de procesar.
3. **Descripción del reporte** (para el nombre del archivo de salida) y botón
   **"Procesar boletas"** — corre la extracción sobre lo cargado y detecta qué monedas
   no-CLP aparecen.
4. **Tipo de cambio**: recién ahí aparecen los campos que dependen de lo detectado — el
   USD → CLP si hace falta, y por cada moneda extranjera que necesita el cálculo de FX
   real (ver "FX real de moneda extranjera" arriba), un selector para elegir la boleta
   de referencia y un campo para el USD que cobró el banco. Reemplaza la selección por
   índice de consola.
5. **"Crear rendición"**: deshabilitado hasta que todo lo anterior esté completo. Al
   generar, ofrece la descarga del Excel de rendición y (si hubo casos) el de
   auditoría, y muestra el mismo resumen de tokens/costo que imprime la CLI.

No reemplaza la CLI — `python src/main.py boletas/ ...` sigue funcionando igual, para
scripting o CI.

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
        (entremedio: se pregunta por consola el FX de cada moneda no-CLP y la
         descripción del reporte — ver "Es interactivo" arriba)
        ▼
5a. excel_writer.py — si se determinó el monto total (esté "OK" o marcada para
        │              revisión): se agrega como fila nueva al Excel de salida (copia
        │              de la plantilla, con las filas de ejemplo limpiadas). FX es 1
        │              para CLP o el valor que ingresó el usuario para esa moneda, y
        │              Amount in CLP queda como fórmula "=FX*Amount",
        │              preservando el dropdown de Currency/Expense Type y la fórmula
        │              de la fila de total que trae la plantilla. También estampa la
        │              fecha de ejecución en los dos campos de fecha del encabezado
        │              (Date Submitted y el Date del bloque de firma).
5b. audit_writer.py — cada boleta marcada para revisión (las OK no) queda en su
                        propia pestaña de auditoria.xlsx: motivo, valores extraídos
                        (monto/moneda/fecha/archivo) y la imagen ORIGINAL de la
                        boleta embebida, para cotejar a simple vista. Más una
                        pestaña índice con hipervínculos a cada caso.
```

Una boleta marcada para revisión **sí se escribe** en el Excel de rendición con los
datos que se pudieron extraer, siempre que se haya determinado el monto total — la
marca de revisión no desaparece, sigue teniendo su pestaña en `auditoria.xlsx` y su
conteo en el resumen de consola, y en la fila del Excel de rendición la columna
Comments avisa que hay que mirar la auditoría (ver más abajo). Si el monto total **no**
se pudo determinar, la boleta no se escribe en el Excel de rendición en absoluto — solo
queda en `auditoria.xlsx` (aunque en la práctica una boleta sin monto siempre queda
para revisión, así que siempre tiene su pestaña).

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
| FX | Sí | `1` para CLP (no se pregunta); `USD` se pregunta directo; el resto se calcula como FX real (regla de 3 en dos pasos) — ver "FX real de moneda extranjera" |
| Amount in CLP | Sí, como fórmula | `=FX*Amount` (ej. `=F9*D9`); se recalcula solo al editar FX a mano |
| Expense Type | Sí | Una de las 22 categorías fijas de la hoja "Cheat Sheet" |
| Comments | Sí | Nombre del archivo de origen, sin extensión; en filas para revisión, ese mismo nombre más el sufijo " (Marcada para Revision)" (ver regla de negocio abajo) |

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

### Pestaña "Complementary info"

El Excel de salida trae, además de "Expense Report", una pestaña `Complementary info -
<MONEDA>` por cada moneda extranjera (distinta de CLP y USD) presente en el reporte —
ver "FX real de moneda extranjera" arriba para el detalle del cálculo que documenta.
Trae la foto de la boleta que elegiste, dos tablas con el cálculo paso a paso, y dos
espacios para tus propios screenshots del banco (listado de movimientos y tipo de
cambio) que **tenés que completar vos a mano** — el programa no los toca. Si ninguna
moneda del reporte necesita este cálculo (todo CLP, o CLP+USD), esta pestaña no aparece.

## Reporte de auditoría

`auditoria.xlsx` (formato configurable en `output.audit_report_path`) es un Excel
separado del de rendición, pensado para revisar de un vistazo qué boletas necesitan
confirmación manual:

- **Una pestaña por boleta marcada para revisión** — las boletas OK no tienen pestaña
  acá, ya quedaron resueltas en su fila del Excel de rendición. Cada pestaña trae el
  motivo por el que se marcó para revisión, los valores que sí se extrajeron (monto,
  moneda, fecha, nombre del archivo de origen), y **la imagen original de la boleta
  embebida** (nunca la versión preprocesada/binarizada — se lee tal como la sacó el
  usuario, y si el origen es un PDF, se rasteriza su primera página a imagen).
- **Pestaña "Índice" primero**, con la lista de todos los casos (archivo + motivo) e
  hipervínculos a cada pestaña, para navegar rápido.
- Nombres de pestaña saneados (sin `: \ / ? * [ ]`) y truncados a 31 caracteres (límite
  de Excel), con sufijo numérico si dos truncan al mismo nombre. El nombre completo del
  archivo siempre queda dentro de la pestaña aunque el título esté truncado.
- **Si la corrida no tuvo boletas para revisión, el archivo no se genera** (y si existe
  uno de una corrida anterior en esa ruta, se borra, para que su ausencia sea una señal
  confiable de "esta corrida no tuvo casos").

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

**Formato de Comments**: en filas "OK", el nombre del archivo de origen de la boleta
sin su extensión (`Path(...).stem`, que remueve solo la última extensión — ej.
`boleta.lima.01.jpg` → `boleta.lima.01`). En filas marcadas para revisión (pero con
monto determinado), Comments es ese mismo nombre sin extensión más el sufijo
" (Marcada para Revision)" — ej. `boleta_taxi_01 (Marcada para Revision)` — para que al
confirmar los datos baste con borrar el sufijo en vez de escribir la descripción desde
cero.

**Boletas para revisión con monto determinado sí se escriben en el Excel**: antes,
cualquier boleta marcada para revisión quedaba excluida del Excel de rendición por
completo. Ahora, si se pudo determinar el monto total, la fila se escribe con los
datos que sí se extrajeron (Amount, Currency, FX, Amount in CLP) — la única diferencia
con una fila OK es el texto de Comments de arriba. La marca de revisión se sigue
registrando igual que antes, con su pestaña en `auditoria.xlsx` y su conteo en el
resumen impreso en consola. Si el monto no se determinó, la boleta sigue sin escribirse
en el Excel de rendición (eso no cambió).

**El FX se determina una vez por moneda**, después de leer todas las boletas, y el mismo
valor se carga en todas las filas de esa moneda — no por boleta. CLP nunca se pregunta,
queda fijo en `1`. USD se pregunta directo; el resto se calcula como FX real (ver "FX
real de moneda extranjera" arriba). Si una fila tiene moneda no determinada (`None`),
queda en FX=1 por no haber moneda contra la cual calcular nada.

## Estructura del proyecto

```
ParserBoletas/
  app.py              # entrypoint único de la interfaz web (python app.py)
  boletas/            # imágenes/PDFs de boletas a procesar
  plantilla/          # Excel de rendición de ejemplo (formato de referencia)
  src/
    preprocess.py     # deskew, denoise, contraste, upscaling, rasterizado de PDF
    extract.py        # extracción de campos por visión (Claude API)
    currency.py       # parsing de números localizados + normalización de moneda
    validate.py       # consistencia de montos + umbral de confianza
    excel_writer.py   # escritura al formato de la plantilla
    complementary_info.py  # FX real por moneda extranjera (regla de 3) + pestaña "Complementary info"
    audit_writer.py   # reporte de auditoría .xlsx (pestaña por boleta a revisar + imagen)
    cost.py           # acumulación de tokens + estimación de costo de la corrida
    api_key.py        # resuelve/guarda la API key (env var > secrets.yaml > prompt)
    main.py           # orquesta el pipeline sobre una carpeta (CLI) + helpers compartidos con la web
    web/
      routes.py       # endpoints FastAPI — fachada sobre la misma lógica de main.py
      state.py        # sesiones ("jobs") en memoria: boletas subidas + resultados intermedios
      templates/index.html  # página única (Tailwind CDN + Alpine.js, sin build de Node)
      static/         # app.css, app.js
  tests/              # pytest, con casos armados a partir de boletas reales
  config.yaml         # parámetros calibrables (nunca secretos)
  secrets.yaml        # API key en texto plano — generado localmente, en .gitignore
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
con monto determinado → se escribe con Comments = nombre de archivo sin extensión +
" (Marcada para Revision)"; boleta OK → mantiene el nombre de archivo sin extensión;
boleta para revisión sin monto → no se escribe (sin cambios); más un test de
integración con tres boletas que confirma que `auditoria.xlsx` tiene pestaña para las
dos boletas REVIEW (no para la OK). `audit_writer.py` (`tests/test_audit_writer.py`, usando boletas reales
de `boletas/` — una jpeg y un PDF, para probar el rasterizado) tiene su propia
cobertura: saneo/truncado/deduplicado de nombres de pestaña, contenido de cada pestaña
(motivo + valores extraídos), que la imagen efectivamente quede embebida (verificado
inspeccionando el .xlsx generado, no solo la API de openpyxl), los hipervínculos del
índice, y que no se genera archivo (y se borra uno preexistente) cuando no hay casos
para revisión; y el paso interactivo de FX/nombre de archivo (`tests/test_main.py`,
mockeando `builtins.input`): saneo de nombre de archivo (caracteres prohibidos,
espacios, guiones bajos repetidos), que la descripción se vuelva a pedir si sanea a
vacío, que acepte punto o coma decimal y vuelva a preguntar ante negativos/cero/texto no
numérico, que USD se pregunte directo sin pasar por selección de boleta, que las demás
monedas calculen su FX real reutilizando el FX de USD (o preguntando el tipo de cambio
USD → CLP aparte si no hay boletas en USD, una sola vez aunque haya varias monedas), y
un test de integración de `run()` que confirma que el FX resultante queda cargado en las
filas de esa moneda mientras CLP queda en 1; `complementary_info.py`
(`tests/test_complementary_info.py`, usando una boleta real y la plantilla real): el
cálculo de FX real contra el ejemplo de referencia (223.50 PEN / 67.41 USD / TC 922 →
278.09), que la pestaña "Complementary info" se elimina cuando no hay monedas que la
necesiten, que se crea una pestaña "Complementary info - <MONEDA>" por cada moneda
extranjera con las tablas y fórmulas correctas, que la imagen embebida es la boleta
elegida (no el ejemplo de la plantilla), que las flechas conectoras sobreviven, que el
resultado final del FX real queda con la misma cantidad de decimales que la columna FX
de "Expense Report" (no el formato sin decimales que trae la plantilla), y que dos
monedas simultáneas generan pestañas independientes; la resolución de la API key
(`tests/test_api_key.py`, mockeando
`getpass.getpass`): la variable de entorno tiene prioridad sobre el archivo, no
pregunta si el archivo ya tiene un token válido, pregunta y guarda cuando no hay nada,
reintenta si el input queda vacío, un token en blanco en el archivo se trata como
ausente, y el archivo queda en UTF-8 con la advertencia de texto plano; y la
compatibilidad con consola Windows (`_ensure_utf8_console` en `tests/test_main.py`):
reconfigura stdout/stderr a UTF-8, tolera streams que no exponen `reconfigure()`, y un
test que reproduce el `UnicodeEncodeError` real contra un stream `cp1252` y confirma
que la reconfiguración lo evita; el guardado del token para la interfaz web
(`has_saved_key`/`save_api_key` en `tests/test_api_key.py`, sin `getpass`); y la capa
web (`tests/test_web.py`, vía `fastapi.testclient.TestClient`, con `main.process_file`
mockeado igual que en `test_main.py`): sube/rechaza extensiones no soportadas, quitar
un archivo antes de parsear, detección de monedas y candidatos por moneda tras
`/parse`, la regla de habilitación de "Crear rendición" (`/validate`) antes y después de
completar los campos de FX, que `/generate` rechace con 400 si faltan requisitos, que
el Excel descargado no tenga pestaña "Complementary info" con solo CLP y sí tenga
"Complementary info - PEN" con el FX real correcto cuando corresponde, y que una boleta
para revisión deje disponible la descarga de `auditoria.xlsx`. No hacen llamadas a la
API de Claude (la llamada de red está aislada y mockeada), así que corren sin necesidad
de `ANTHROPIC_API_KEY`.

## Fuera de alcance en v1

- Conversión de divisas automática vía un servicio externo de tipo de cambio: el FX real
  se calcula a partir de datos que ingresa el usuario (boleta elegida + USD cobrado por
  el banco), no se consulta ningún servicio.
- No hay modo no interactivo/batch: tanto la CLI como la interfaz web piden estos datos
  (por consola o por formulario) en cada corrida.
- Categorización difusa avanzada más allá de mapear a la lista fija de 23 tipos de gasto.
- Integración con correo/buzón de gastos.
- Multi-usuario / despliegue remoto: la interfaz web es para un solo usuario local (el
  estado de cada sesión vive en memoria del proceso, no hay autenticación).
