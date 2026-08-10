#!/usr/bin/env node
// Genera un .zip usando LA MISMA lógica de exportación que corre en el
// navegador (pwa/js/export-zip.js) — no una reimplementación aparte que se
// pueda desalinear del contrato real. Existe únicamente para que
// tests/test_pwa_export_contract.py (en la app de PC) pueda correr un
// round-trip real: este script arma el .zip con Node, y ese test lo importa
// con receipt_collections.import_collection_from_zip de verdad.
//
// Uso: node build_test_zip.js <ruta-salida.zip> [nombre-coleccion]
//
// Requiere `npm install` corrido antes en pwa/ (trae jszip como devDependency).
"use strict";

const fs = require("fs");
const path = require("path");

global.JSZip = require("jszip");
const { ParserBoletasExport } = require("../js/export-zip.js");
const { ParserBoletasDB } = require("../js/db.js");

async function main() {
  const [, , outputPath, collectionName] = process.argv;
  if (!outputPath) {
    console.error("Uso: node build_test_zip.js <ruta-salida.zip> [nombre-coleccion]");
    process.exit(1);
  }

  const collection = { name: collectionName || "Coleccion Prueba PWA" };
  // Contenido de boleta ficticio — este script prueba el CONTRATO del zip
  // (estructura/metadata), no la legibilidad de la imagen para el modelo de
  // visión (eso ya lo cubre scripts/generar_coleccion_prueba.py del lado PC).
  // Una de las boletas usa un nombre "descripción del gasto" con espacios
  // (mismo saneo que aplica renameReceipt en la app real, ParserBoletasDB.
  // sanitizeReceiptName) para probar que el contrato tolera espacios de punta
  // a punta, no solo los nombres genéricos "boleta_*".
  const describedStem = ParserBoletasDB.sanitizeReceiptName("  almuerzo con  cliente   dos personas  ");
  const receipts = [
    { filename: "boleta_clp.jpg", blob: Buffer.from("contenido-fake-clp") },
    { filename: "boleta_usd.jpg", blob: Buffer.from("contenido-fake-usd") },
    { filename: `${describedStem}.jpg`, blob: Buffer.from("contenido-fake-pen") },
  ];

  const zipBlob = await ParserBoletasExport.buildZip(collection, receipts);
  const buffer = Buffer.from(await zipBlob.arrayBuffer());

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  console.log(`ZIP generado: ${outputPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
