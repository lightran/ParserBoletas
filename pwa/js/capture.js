// Normalización de imágenes capturadas (cámara o galería) a JPEG reescalado,
// dibujándolas en un <canvas>. Resuelve dos problemas de una:
//
// - HEIC: las fotos de la app Cámara de iPhone suelen guardarse en HEIC, que
//   la app de PC podría no procesar bien. Safari sabe decodificar HEIC al
//   cargarlo en un <img> (WebKit lo soporta a nivel de sistema); redibujarlo
//   en canvas y exportar con toBlob("image/jpeg") lo convierte a JPEG real
//   sin ninguna librería de conversión.
// - Tamaño: las fotos de celular pesan varios MB. Reescalar al lado mayor a
//   ~2000px mantiene la boleta legible mientras baja mucho el peso, tanto
//   para IndexedDB como para el .zip exportado.
"use strict";

const ParserBoletasCapture = (() => {
  const MAX_DIMENSION = 2000;
  const JPEG_QUALITY = 0.85;

  function loadImage(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error(`No se pudo leer la imagen "${file.name || "sin nombre"}".`));
      };
      img.src = url;
    });
  }

  function computeTargetSize(width, height, maxDimension) {
    const longest = Math.max(width, height);
    if (longest <= maxDimension) return { width, height };
    const scale = maxDimension / longest;
    return { width: Math.round(width * scale), height: Math.round(height * scale) };
  }

  return {
    MAX_DIMENSION,

    async normalizeToJpeg(file, { maxDimension = MAX_DIMENSION, quality = JPEG_QUALITY } = {}) {
      const img = await loadImage(file);
      const { width, height } = computeTargetSize(img.naturalWidth, img.naturalHeight, maxDimension);
      if (!width || !height) {
        throw new Error(`"${file.name || "la imagen"}" no parece ser una imagen válida.`);
      }

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, width, height);

      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(
          (result) => {
            if (result) resolve(result);
            else reject(new Error("No se pudo convertir la imagen a JPEG."));
          },
          "image/jpeg",
          quality
        );
      });

      return blob;
    },
  };
})();
