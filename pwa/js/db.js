// Wrapper de IndexedDB: colecciones + boletas (como Blob) del lado del celular.
// Esta es la ÚNICA persistencia de la PWA — no hay backend, no hay red. Se
// expone como el objeto global `ParserBoletasDB` (sin módulos ES, para poder
// cargarlo con un <script> plano igual que Alpine/JSZip vendorizados).
//
// Esquema:
//   collections  { id, name, createdAt }               keyPath: id
//   receipts     { id, collectionId, filename, blob, addedAt }  keyPath: id
//                índice "by_collection" sobre collectionId
"use strict";

const ParserBoletasDB = (() => {
  const DB_NAME = "parserboletas-pwa";
  const DB_VERSION = 1;
  const STORE_COLLECTIONS = "collections";
  const STORE_RECEIPTS = "receipts";
  const INDEX_BY_COLLECTION = "by_collection";

  let dbPromise = null;

  function openDatabase() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_COLLECTIONS)) {
          db.createObjectStore(STORE_COLLECTIONS, { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains(STORE_RECEIPTS)) {
          const receipts = db.createObjectStore(STORE_RECEIPTS, { keyPath: "id" });
          receipts.createIndex(INDEX_BY_COLLECTION, "collectionId", { unique: false });
        }
      };

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return dbPromise;
  }

  function promisifyRequest(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function withStore(storeNames, mode, run) {
    const db = await openDatabase();
    const tx = db.transaction(storeNames, mode);
    const result = run(tx);
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    // Fallback para navegadores/webviews sin crypto.randomUUID (poco probable
    // en Safari iOS moderno, pero barato de cubrir).
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  return {
    async createCollection(name) {
      const trimmed = (name || "").trim();
      if (!trimmed) throw new Error("El nombre de la colección no puede quedar vacío.");
      const record = { id: uuid(), name: trimmed, createdAt: new Date().toISOString() };
      await withStore([STORE_COLLECTIONS], "readwrite", (tx) => {
        tx.objectStore(STORE_COLLECTIONS).add(record);
      });
      return record;
    },

    async listCollections() {
      const collections = await withStore([STORE_COLLECTIONS], "readonly", (tx) =>
        promisifyRequest(tx.objectStore(STORE_COLLECTIONS).getAll())
      );
      const withCounts = await Promise.all(
        collections.map(async (c) => ({ ...c, receiptCount: await this.countReceipts(c.id) }))
      );
      return withCounts.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    },

    async getCollection(id) {
      const record = await withStore([STORE_COLLECTIONS], "readonly", (tx) =>
        promisifyRequest(tx.objectStore(STORE_COLLECTIONS).get(id))
      );
      if (!record) throw new Error("Colección no encontrada.");
      return record;
    },

    async deleteCollection(id) {
      const receipts = await this.listReceipts(id);
      await withStore([STORE_COLLECTIONS, STORE_RECEIPTS], "readwrite", (tx) => {
        tx.objectStore(STORE_COLLECTIONS).delete(id);
        const receiptsStore = tx.objectStore(STORE_RECEIPTS);
        for (const receipt of receipts) receiptsStore.delete(receipt.id);
      });
    },

    async addReceipt(collectionId, filename, blob) {
      const record = {
        id: uuid(),
        collectionId,
        filename,
        blob,
        addedAt: new Date().toISOString(),
      };
      await withStore([STORE_RECEIPTS], "readwrite", (tx) => {
        tx.objectStore(STORE_RECEIPTS).add(record);
      });
      return record;
    },

    async listReceipts(collectionId) {
      const receipts = await withStore([STORE_RECEIPTS], "readonly", (tx) =>
        promisifyRequest(tx.objectStore(STORE_RECEIPTS).index(INDEX_BY_COLLECTION).getAll(collectionId))
      );
      return receipts.sort((a, b) => a.addedAt.localeCompare(b.addedAt));
    },

    async countReceipts(collectionId) {
      return withStore([STORE_RECEIPTS], "readonly", (tx) =>
        promisifyRequest(tx.objectStore(STORE_RECEIPTS).index(INDEX_BY_COLLECTION).count(collectionId))
      );
    },

    async deleteReceipt(receiptId) {
      await withStore([STORE_RECEIPTS], "readwrite", (tx) => {
        tx.objectStore(STORE_RECEIPTS).delete(receiptId);
      });
    },

    // Nombre de archivo por defecto al agregar una boleta — se usa tal cual si
    // el usuario no le pone un nombre propio (ver renameReceipt más abajo).
    generateReceiptFilename() {
      const stamp = new Date()
        .toISOString()
        .replace(/[-:]/g, "")
        .replace("T", "_")
        .slice(0, 15);
      const random = Math.random().toString(36).slice(2, 6);
      return `boleta_${stamp}_${random}.jpg`;
    },

    // Sanea el nombre editable de una boleta — mismo criterio que
    // main.py::sanitize_receipt_name en la app de PC: reemplaza los
    // caracteres prohibidos en un nombre de archivo (/ \ : * ? " < > |) por
    // "_", pero PRESERVA los espacios (solo colapsa repeticiones) — a
    // diferencia del saneo del nombre de colección. Este texto termina siendo
    // la columna Comments del Excel de rendición (vía Path.stem del nombre de
    // archivo), así que "Almuerzo cliente X" tiene que sobrevivir tal cual.
    sanitizeReceiptName(text) {
      return (text || "")
        .replace(/[\\/:*?"<>|]/g, "_")
        .replace(/\s+/g, " ")
        .trim();
    },

    // Nombre de archivo único dentro de la colección: si "<stem>.jpg" ya lo
    // usa otra boleta, agrega "-2", "-3", ... hasta encontrar uno libre.
    // `excludeReceiptId` se usa al renombrar, para no chocar contra el propio
    // registro que se está renombrando.
    async resolveUniqueFilename(collectionId, stem, extension, excludeReceiptId = null) {
      const existing = await this.listReceipts(collectionId);
      const taken = new Set(
        existing.filter((r) => r.id !== excludeReceiptId).map((r) => r.filename.toLowerCase())
      );
      let candidate = `${stem}${extension}`;
      let suffix = 2;
      while (taken.has(candidate.toLowerCase())) {
        candidate = `${stem}-${suffix}${extension}`;
        suffix += 1;
      }
      return candidate;
    },

    // Renombra una boleta ya guardada: sanea `newName`, resuelve colisiones
    // con otras boletas de la misma colección, y persiste. La extensión
    // (".jpg" — la PWA siempre normaliza a JPEG, ver capture.js) no la edita
    // el usuario, se agrega sola. Lanza si el nombre saneado queda vacío.
    async renameReceipt(receiptId, collectionId, newName) {
      const sanitized = this.sanitizeReceiptName(newName);
      if (!sanitized) throw new Error("El nombre no puede quedar vacío.");

      const filename = await this.resolveUniqueFilename(collectionId, sanitized, ".jpg", receiptId);

      await withStore([STORE_RECEIPTS], "readwrite", (tx) => {
        const store = tx.objectStore(STORE_RECEIPTS);
        const getRequest = store.get(receiptId);
        getRequest.onsuccess = () => {
          const record = getRequest.result;
          if (record) {
            record.filename = filename;
            store.put(record);
          }
        };
      });

      return filename;
    },
  };
})();

// Exponer para Node (test de round-trip del saneo de nombres) sin afectar el
// uso normal en el navegador, donde `module` no existe. Solo se llaman desde
// ahí las funciones puras (sanitizeReceiptName) — nada que toque indexedDB.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { ParserBoletasDB };
}
