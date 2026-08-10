// Lógica de la PWA (Alpine.js). Sin build, sin framework de componentes — un
// solo objeto de estado con dos vistas ("collections" / "detail"), igual de
// espíritu que la SPA de la app de escritorio (src/web/static/app.js).
"use strict";

function parserBoletasApp() {
  return {
    view: "collections", // "collections" | "detail"

    collections: [],
    loadingCollections: false,
    newCollectionName: "",
    creatingCollection: false,

    activeCollection: null,
    receipts: [],
    processingCount: 0, // fotos siendo normalizadas ahora mismo (cámara/galería)

    exporting: false,
    error: null,
    toast: null,

    isStandalone: false,
    showInstallHint: false,

    async init() {
      this.isStandalone =
        window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
      this.showInstallHint = !this.isStandalone;

      await this.loadCollections();
      registerServiceWorker();
    },

    // --- Colecciones -------------------------------------------------------------

    async loadCollections() {
      this.loadingCollections = true;
      try {
        this.collections = await ParserBoletasDB.listCollections();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loadingCollections = false;
      }
    },

    async createCollection() {
      if (!this.newCollectionName.trim() || this.creatingCollection) return;
      this.creatingCollection = true;
      this.error = null;
      try {
        const collection = await ParserBoletasDB.createCollection(this.newCollectionName);
        this.newCollectionName = "";
        await this.openCollection(collection.id);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.creatingCollection = false;
      }
    },

    async openCollection(id) {
      this.error = null;
      try {
        this.activeCollection = await ParserBoletasDB.getCollection(id);
        this.receipts = await ParserBoletasDB.listReceipts(id);
        this.view = "detail";
      } catch (e) {
        this.error = e.message;
      }
    },

    goToCollections() {
      this.view = "collections";
      this.activeCollection = null;
      this.releaseReceiptUrls();
      this.receipts = [];
      this.loadCollections();
    },

    async deleteCollection(id, event) {
      event.stopPropagation();
      if (!window.confirm("¿Eliminar esta colección y todas sus boletas? No se puede deshacer.")) return;
      this.error = null;
      try {
        await ParserBoletasDB.deleteCollection(id);
        await this.loadCollections();
      } catch (e) {
        this.error = e.message;
      }
    },

    // --- Boletas: cámara / galería / eliminar ------------------------------------

    async onFilesChosen(event) {
      const files = Array.from(event.target.files || []);
      event.target.value = ""; // permite volver a elegir el mismo archivo después
      if (files.length) await this.addFiles(files);
    },

    async addFiles(files) {
      this.error = null;
      this.processingCount = files.length;
      for (const file of files) {
        try {
          const blob = await ParserBoletasCapture.normalizeToJpeg(file);
          const filename = ParserBoletasDB.generateReceiptFilename();
          const record = await ParserBoletasDB.addReceipt(this.activeCollection.id, filename, blob);
          this.receipts.push(record);
        } catch (e) {
          this.error = `No se pudo procesar "${file.name}": ${e.message}`;
        } finally {
          this.processingCount = Math.max(0, this.processingCount - 1);
        }
      }
    },

    async deleteReceipt(id) {
      this.error = null;
      try {
        await ParserBoletasDB.deleteReceipt(id);
        const receipt = this.receipts.find((r) => r.id === id);
        if (receipt && receipt._url) URL.revokeObjectURL(receipt._url);
        this.receipts = this.receipts.filter((r) => r.id !== id);
      } catch (e) {
        this.error = e.message;
      }
    },

    receiptUrl(receipt) {
      if (!receipt._url) receipt._url = URL.createObjectURL(receipt.blob);
      return receipt._url;
    },

    // Nombre mostrado bajo la miniatura: sin extensión, igual criterio que la
    // columna Comments del Excel en la app de PC (Path.stem del archivo).
    stemOf(filename) {
      const idx = filename.lastIndexOf(".");
      return idx > 0 ? filename.slice(0, idx) : filename;
    },

    // Tocar el nombre bajo una miniatura para editarlo — es la descripción
    // del gasto (ej. "Almuerzo con cliente dos personas"), porque ese nombre
    // de archivo termina siendo la columna Comments del Excel al importar en
    // la app de PC. Sin nombre propio, queda el que se le puso al agregarla.
    async renameReceipt(receipt) {
      const input = window.prompt("Nombre de la boleta (descripción del gasto):", this.stemOf(receipt.filename));
      if (input === null) return; // canceló
      const sanitized = ParserBoletasDB.sanitizeReceiptName(input);
      if (!sanitized) return; // vacío después de sanear: no cambia nada

      this.error = null;
      try {
        const finalFilename = await ParserBoletasDB.renameReceipt(receipt.id, this.activeCollection.id, sanitized);
        receipt.filename = finalFilename;
        if (finalFilename.toLowerCase() !== `${sanitized.toLowerCase()}.jpg`) {
          this.toast = `Ya había una boleta con ese nombre — se guardó como "${this.stemOf(finalFilename)}".`;
          setTimeout(() => {
            this.toast = null;
          }, 4000);
        }
      } catch (e) {
        this.error = e.message;
      }
    },

    releaseReceiptUrls() {
      for (const receipt of this.receipts) {
        if (receipt._url) URL.revokeObjectURL(receipt._url);
      }
    },

    // --- Exportar ------------------------------------------------------------------

    async exportCollection() {
      if (this.exporting) return;
      if (!this.receipts.length) {
        this.error = "Agrega al menos una boleta antes de exportar.";
        return;
      }
      this.exporting = true;
      this.error = null;
      try {
        const zipBlob = await ParserBoletasExport.buildZip(this.activeCollection, this.receipts);
        const filename = ParserBoletasExport.zipFilenameFor(this.activeCollection.name);
        await this.shareOrDownload(zipBlob, filename);
        this.toast = "Colección exportada.";
        setTimeout(() => {
          this.toast = null;
        }, 3000);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.exporting = false;
      }
    },

    async shareOrDownload(blob, filename) {
      const file = new File([blob], filename, { type: "application/zip" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        try {
          await navigator.share({ files: [file], title: filename });
          return;
        } catch (e) {
          if (e.name === "AbortError") return; // el usuario cerró el share sheet sin elegir nada
          // cualquier otro error de share cae a descarga directa
        }
      }
      this.downloadBlob(blob, filename);
    },

    downloadBlob(blob, filename) {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  };
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  // Sin esperar el evento "load": para cuando Alpine corre init() la página
  // ya está cargada casi siempre, y si se esperara "load" acá podría no
  // dispararse nunca (el evento ya pasó antes de engancharse a él).
  navigator.serviceWorker.register("./service-worker.js").catch((err) => {
    console.error("No se pudo registrar el service worker:", err);
  });
}
