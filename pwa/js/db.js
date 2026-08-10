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

    // Nombre de archivo único dentro de una colección — la PWA no pide
    // describir cada boleta (eso se hace después, renombrando en la app de
    // PC, que es donde ese nombre importa para la columna Comments del Excel).
    generateReceiptFilename() {
      const stamp = new Date()
        .toISOString()
        .replace(/[-:]/g, "")
        .replace("T", "_")
        .slice(0, 15);
      const random = Math.random().toString(36).slice(2, 6);
      return `boleta_${stamp}_${random}.jpg`;
    },
  };
})();
