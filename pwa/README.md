# ParserBoletas — Captura (PWA)

App web instalable (PWA) para capturar boletas desde el celular, organizarlas en
colecciones locales, y exportarlas como `.zip` para importarlas en
[ParserBoletas de escritorio](../README.md).

**Rol acotado, a propósito**: esta app solo captura, organiza y exporta. No extrae
datos, no llama a ninguna API de IA, no genera ninguna rendición ni Excel — todo eso
sigue pasando en la app de PC al importar el `.zip` (ver `../src/receipt_collections.py`).
No hay ninguna lógica de negocio duplicada acá.

Pensada para iPhone (PWA vía Safari, ya que no hay Mac disponible para compilar una
app nativa de iOS), pero funciona igual en cualquier navegador moderno.

## Probar en local

```bash
cd pwa
python -m http.server 8000
```

Abrí `http://localhost:8000/` — `localhost` cuenta como contexto seguro para el
navegador, así que el service worker, la cámara y el resto de las APIs de PWA
funcionan igual que en producción (HTTPS real).

## Deploy (GitHub Pages, vía GitHub Actions)

1. En el repo de GitHub, **Settings → Pages → Build and deployment → Source**:
   elegí **"GitHub Actions"** (una sola vez).
2. Cualquier push a `main` que toque algo dentro de `pwa/` dispara
   `.github/workflows/deploy-pwa.yml`, que sube esta carpeta tal cual (son
   archivos estáticos, sin build) y la publica.
3. También se puede disparar a mano desde la pestaña **Actions** del repo
   ("Run workflow") sin necesidad de un commit nuevo.
4. URL resultante: `https://<usuario>.github.io/<repo>/pwa/` (para este repo,
   `https://lightran.github.io/ParserBoletas/pwa/`).

HTTPS es obligatorio para que la PWA funcione fuera de `localhost` (service worker,
cámara, instalación) — GitHub Pages lo da gratis, por eso no hace falta configurar
nada aparte.

## Instalar en iPhone

iOS no ofrece un prompt automático de instalación — hay que hacerlo a mano:

1. Abrí la URL de la PWA en **Safari** (tiene que ser Safari, no Chrome/Firefox — son
   los únicos con el motor que soporta instalar PWAs en iOS).
2. Tocá el ícono de **Compartir** (el cuadrado con la flecha hacia arriba).
3. Elegí **"Agregar a inicio"**.
4. Confirmá el nombre y tocá **"Agregar"**.

Queda un ícono en la pantalla de inicio que abre la app en modo standalone (sin la
barra de Safari). La propia app muestra este mismo recordatorio la primera vez que se
abre desde el navegador (no en modo instalado).

**Aviso importante sobre almacenamiento**: iOS puede borrar los datos de una PWA
(incluidas las boletas guardadas) si pasa mucho tiempo sin abrirla o si el
dispositivo necesita liberar espacio. Tratá el celular como un lugar de **paso**, no
de almacenamiento permanente — exportá cada colección relativamente pronto después
de cargar las boletas. La app lo recuerda con un aviso en la pantalla de cada
colección.

## Cómo probar el round-trip completo (celular → PC)

1. En la PWA: creá una colección, agregá una o más boletas (foto o galería), y
   exportá — el share sheet de iOS ofrece AirDrop, Mail, Mensajes, guardar en
   Archivos, etc. Si el navegador no soporta compartir archivos, descarga el `.zip`
   directo.
2. Pasá ese `.zip` al PC por el medio que prefieras.
3. En ParserBoletas de escritorio: **Colecciones → "Importar colección (ZIP)"**,
   elegí el archivo.
4. La colección debe aparecer con todas sus boletas, lista para generar la
   rendición con el flujo normal.

Para probar el contrato del ZIP sin depender de un iPhone real, hay dos maneras:

- **`tests/test_pwa_export_contract.py`** (en la raíz del repo, corre con `pytest`):
  arma un `.zip` con Node ejecutando literalmente `js/export-zip.js` (el mismo
  código que corre en el navegador) y lo importa con el código Python real de
  `receipt_collections.py`. Requiere `npm install` corrido una vez en esta carpeta
  (`pwa/node_modules/jszip` — dependencia de desarrollo, no de la PWA en sí).
- A mano, en cualquier navegador de escritorio: abrí la PWA, creá una colección de
  prueba, subí un par de imágenes cualquiera, exportá (cae a descarga si el
  navegador no soporta compartir archivos), e importá ese `.zip` en la app de PC.

## Estructura

```
pwa/
  index.html            # página única (dos vistas: colecciones / detalle)
  manifest.json          # metadata de instalación (nombre, íconos, colores)
  service-worker.js      # cache-first del app shell — funciona offline
  css/app.css             # mobile-first, escrito a mano (sin CDN, offline-safe)
  js/
    db.js                 # IndexedDB: colecciones + boletas (Blob)
    capture.js             # canvas: normaliza a JPEG (resuelve HEIC) + reescala (~2000px)
    export-zip.js           # arma el .zip con el contrato exacto del importador
    app.js                  # Alpine.js: vistas, cámara/galería, export/share
  vendor/
    alpine.min.js            # Alpine.js 3.16.0, vendorizado (no CDN)
    jszip.min.js               # JSZip 3.10.1, vendorizado (no CDN)
  icons/
    icon-192.png, icon-512.png
  scripts/
    build_test_zip.js         # arma un .zip de prueba con Node — usado por
                               # tests/test_pwa_export_contract.py
  package.json                # única dependencia de DEV (jszip, para el test de
                               # round-trip) — la PWA en sí no tiene runtime de Node
```

**Por qué todo vendorizado y sin build**: la PWA tiene que funcionar sin conexión
desde el primer uso después de instalada. Un `<script src="cdn...">` fallaría si el
primer uso es offline antes de que el service worker haya podido cachear esa
respuesta externa. Vendorizando Alpine/JSZip como archivos propios, el service
worker los cachea como cualquier otro recurso same-origin — cero dependencia de red
después de la primera carga. Mismo motivo para no usar Tailwind (que necesita su
runtime JS vía CDN): el CSS está escrito a mano en `css/app.css`.

## Contrato del ZIP (referencia)

Ver el docstring de `../src/receipt_collections.py` (sección "Import desde ZIP")
para la fuente de verdad, y `../scripts/generar_coleccion_prueba.py` para un
generador de referencia en Python del mismo formato. Resumen:

```
<NombreColeccion>.zip
├── coleccion.json   # {"version": 1, "name": "...", "receipts": ["a.jpg", ...], "created_at": "ISO 8601"}
└── boletas/
    ├── a.jpg
    └── ...
```

- `version`: entero, debe ser el que el importador soporta (hoy `1`).
- `name`: string no vacío.
- `receipts`: nombres de archivo planos (sin subcarpetas) que coincidan exactamente
  con lo que hay en `boletas/` — ni de más ni de menos.
- `created_at`: ISO 8601 (el importador no valida el formato estrictamente, pero se
  genera bien formado por consistencia).
- **`last_generated_at` NO va acá** — es un campo que solo existe en el
  `coleccion.json` *local* que la app de PC reconstruye después de importar (para
  registrar cuándo se generó la última rendición, algo que la PWA no puede saber).
