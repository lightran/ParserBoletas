function expenseApp() {
  return {
    jobId: null,
    hasApiKey: null,
    apiKeyInput: "",
    savingApiKey: false,

    files: [],
    dragOver: false,

    description: "",

    parsing: false,
    parsed: false,
    parseResult: null,
    usdFx: null,
    conversionSelections: {},

    ready: false,
    missing: [],

    generating: false,
    generateResult: null,

    error: null,

    steps: [
      { key: "upload", n: "1", label: "Cargar boletas" },
      { key: "process", n: "2", label: "Procesar" },
      { key: "fx", n: "3", label: "Tipo de cambio" },
      { key: "generate", n: "4", label: "Generar" },
    ],

    async init() {
      try {
        const statusRes = await fetch("/api/config-status");
        const status = await statusRes.json();
        this.hasApiKey = status.has_api_key;

        const jobRes = await fetch("/api/jobs", { method: "POST" });
        const job = await jobRes.json();
        this.jobId = job.job_id;
      } catch (e) {
        this.error = "No se pudo inicializar la sesión. Recarga la página.";
      }
    },

    currentStep() {
      if (this.generateResult) return "generate";
      if (this.parsed) return "fx";
      if (this.files.length) return "process";
      return "upload";
    },

    stepDone(key) {
      const order = ["upload", "process", "fx", "generate"];
      return order.indexOf(key) < order.indexOf(this.currentStep());
    },

    async saveApiKey() {
      this.savingApiKey = true;
      this.error = null;
      try {
        const res = await fetch("/api/config/api-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: this.apiKeyInput }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Error guardando la key.");
        this.hasApiKey = true;
        this.apiKeyInput = "";
      } catch (e) {
        this.error = e.message;
      } finally {
        this.savingApiKey = false;
      }
    },

    onFileDrop(event) {
      this.dragOver = false;
      this.uploadFiles(event.dataTransfer.files);
    },

    onFileInput(event) {
      this.uploadFiles(event.target.files);
      event.target.value = "";
    },

    async uploadFiles(fileList) {
      if (!this.jobId || !fileList.length) return;
      const formData = new FormData();
      for (const file of fileList) formData.append("files", file);

      this.error = null;
      try {
        const res = await fetch(`/api/jobs/${this.jobId}/receipts`, {
          method: "POST",
          body: formData,
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Error subiendo boletas.");
        const data = await res.json();
        this.files = data.files;
        this.parsed = false;
        this.parseResult = null;
        this.generateResult = null;
        if (data.rejected && data.rejected.length) {
          this.error = "Archivos no soportados (se ignoraron): " + data.rejected.join(", ");
        }
        this.checkReady();
      } catch (e) {
        this.error = e.message;
      }
    },

    async removeFile(name) {
      if (!this.jobId) return;
      try {
        const res = await fetch(
          `/api/jobs/${this.jobId}/receipts/${encodeURIComponent(name)}`,
          { method: "DELETE" }
        );
        const data = await res.json();
        this.files = data.files;
        this.parsed = false;
        this.parseResult = null;
        this.generateResult = null;
        this.checkReady();
      } catch (e) {
        this.error = "No se pudo quitar el archivo.";
      }
    },

    async parseReceipts() {
      if (!this.jobId || !this.files.length) return;
      this.parsing = true;
      this.error = null;
      try {
        const res = await fetch(`/api/jobs/${this.jobId}/parse`, { method: "POST" });
        if (!res.ok) throw new Error((await res.json()).detail || "Error procesando boletas.");
        this.parseResult = await res.json();
        this.parsed = true;

        this.conversionSelections = {};
        for (const code of this.parseResult.conversion_currencies) {
          const candidates = this.parseResult.candidates_by_currency[code] || [];
          this.conversionSelections[code] = {
            filename: candidates.length ? candidates[0].filename : "",
            usd_charged: null,
          };
        }
        this.usdFx = null;
        await this.checkReady();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.parsing = false;
      }
    },

    _conversionsPayload() {
      if (!this.parseResult) return [];
      return this.parseResult.conversion_currencies
        .map((code) => {
          const sel = this.conversionSelections[code];
          if (!sel || !sel.filename || !sel.usd_charged) return null;
          return { currency: code, filename: sel.filename, usd_charged: sel.usd_charged };
        })
        .filter(Boolean);
    },

    async checkReady() {
      if (!this.jobId || !this.parsed) {
        this.ready = false;
        return;
      }
      try {
        const res = await fetch(`/api/jobs/${this.jobId}/validate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            description: this.description,
            usd_fx: this.usdFx,
            conversions: this._conversionsPayload(),
          }),
        });
        const data = await res.json();
        this.ready = data.ready;
        this.missing = data.missing;
      } catch (e) {
        this.ready = false;
      }
    },

    async generate() {
      if (!this.jobId || !this.ready) return;
      this.generating = true;
      this.error = null;
      try {
        const res = await fetch(`/api/jobs/${this.jobId}/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            description: this.description,
            usd_fx: this.usdFx,
            conversions: this._conversionsPayload(),
          }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Error generando la rendición.");
        this.generateResult = await res.json();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.generating = false;
      }
    },
  };
}
