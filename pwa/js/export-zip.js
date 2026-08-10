// Arma el .zip de una colección con el contrato EXACTO que exige el importador
// de la app de PC (`receipt_collections.import_collection_from_zip`, verificado
// contra el código fuente real — no documentación aparte que se pueda desalinear):
//
//   <nombre>.zip
//   ├── coleccion.json   { version, name, receipts: ["a.jpg", ...], created_at }
//   └── boletas/
//       ├── a.jpg
//       └── ...
//
// - version: entero, debe ser el que el importador soporta (hoy 1).
// - name: string no vacío.
// - receipts: nombres de archivo PLANOS (sin subcarpetas) que coincidan
//   exactamente con lo que se guarda en boletas/ — ni de más ni de menos.
// - created_at: ISO 8601 (el importador no valida el formato estrictamente,
//   pero se genera bien formado para ser consistente con el resto de la app).
//
// `tests/test_pwa_export_contract.py` (en el repo de la app de PC) corre este
// mismo módulo con Node contra el importador Python real, así que si el
// contrato cambia de un lado, el test lo detecta del otro.
"use strict";

const ParserBoletasExport = (() => {
  const METADATA_VERSION = 1;

  function sanitizeFilenameComponent(text) {
    // Mismo criterio que main.py::sanitize_filename_component en la app de PC:
    // caracteres prohibidos del sistema de archivos y espacios -> "_",
    // colapsando repeticiones, sin "_" al principio/final.
    return (text || "")
      .replace(/[\\/:*?"<>|]/g, "_")
      .replace(/\s+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  return {
    METADATA_VERSION,

    buildManifest(collection, receipts) {
      return {
        version: METADATA_VERSION,
        name: collection.name,
        receipts: receipts.map((r) => r.filename),
        created_at: new Date().toISOString(),
      };
    },

    async buildZip(collection, receipts) {
      if (!collection || !collection.name || !collection.name.trim()) {
        throw new Error("La colección necesita un nombre para exportarse.");
      }
      if (!receipts || !receipts.length) {
        throw new Error("La colección no tiene boletas para exportar.");
      }

      const zip = new JSZip();
      const manifest = this.buildManifest(collection, receipts);
      zip.file("coleccion.json", JSON.stringify(manifest, null, 2));

      const boletasFolder = zip.folder("boletas");
      for (const receipt of receipts) {
        boletasFolder.file(receipt.filename, receipt.blob);
      }

      return zip.generateAsync({ type: "blob", compression: "DEFLATE" });
    },

    zipFilenameFor(collectionName) {
      const sanitized = sanitizeFilenameComponent(collectionName);
      return `${sanitized || "coleccion"}.zip`;
    },
  };
})();

// Exponer para Node (test de round-trip) sin afectar el uso normal en el
// navegador, donde `module` no existe.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { ParserBoletasExport };
}
