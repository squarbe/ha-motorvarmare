/* Motorvärmare – Lovelace-kort (version 0.5). Inga externa beroenden.
 *
 * type: custom:motorvarmare-card          -> alla uttag, nya uttag dyker upp automatiskt
 * type: custom:motorvarmare-card
 * entity: sensor.<uttag>_avresor          -> ett uttag
 */
const MV_VERSION = "0.5.0";

/** Alla uttagens Avresor-sensorer (de har attributet heater_id och trips), sorterade på namn. */
function mvHeaterEntities(hass) {
  return Object.keys(hass.states)
    .filter((id) => {
      const a = hass.states[id].attributes;
      return id.startsWith("sensor.") && a.heater_id && Array.isArray(a.trips);
    })
    .sort((x, y) => mvName(hass, x).localeCompare(mvName(hass, y), "sv"));
}

function mvName(hass, entityId) {
  const st = hass.states[entityId];
  const n = (st && st.attributes.friendly_name) || entityId;
  return n.replace(/ Avresor$/, "");
}

/** Effektsensorn på reläets enhet (t.ex. Shellyns Power), om den finns. */
function mvPowerEntity(hass, relayEntity) {
  if (!relayEntity || !hass.entities || !hass.entities[relayEntity]) return null;
  const device = hass.entities[relayEntity].device_id;
  if (!device) return null;
  return (
    Object.values(hass.entities).find(
      (e) =>
        e.device_id === device &&
        e.entity_id.startsWith("sensor.") &&
        hass.states[e.entity_id] &&
        hass.states[e.entity_id].attributes.device_class === "power",
    ) || {}
  ).entity_id || null;
}

class MotorvarmareCard extends HTMLElement {
  setConfig(config) {
    this.config = { ...config };
    this._editing = null;
    this._confirmDelete = null;
    this._errors = {};
    this._drafts = {};
    this._key = null;
    if (this._hass) this.render();
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("motorvarmare-card-editor");
  }

  getCardSize() {
    return 6 * Math.max(1, this.entities().length);
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6 };
  }

  entities() {
    if (!this._hass) return [];
    if (this.config.entity) return [this.config.entity];
    return mvHeaterEntities(this._hass);
  }

  set hass(hass) {
    this._hass = hass;
    const parts = this.entities().map((id) => {
      const st = hass.states[id];
      const power = st ? mvPowerEntity(hass, st.attributes.relay_entity) : null;
      return [id, st ? st.state : null, st ? st.attributes : null, power ? hass.states[power].state : null];
    });
    const key = JSON.stringify(parts);
    if (key === this._key) return;
    // Rita inte om medan användaren står i ett fält i kortet; det görs när fältet lämnas.
    const root = this.getRootNode();
    const active = root && root.activeElement;
    if (active && active !== this && this.contains(active) && active.tagName === "INPUT") {
      this._pending = true;
      return;
    }
    this._key = key;
    this.render();
  }

  rerender() {
    this._key = null;
    this.render();
  }

  async call(entityId, service, data) {
    this._errors[entityId] = "";
    try {
      const id = this._hass.states[entityId].attributes.heater_id;
      await this._hass.callService("motorvarmare", service, { heater_id: id, ...data });
    } catch (e) {
      this._errors[entityId] = e.message || String(e);
    }
    this.rerender();
  }

  local(iso) {
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  fmt(iso, withDay = true) {
    const o = withDay
      ? { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" };
    return new Date(iso).toLocaleString("sv-SE", o);
  }

  el(tag, props = {}, ...children) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    if (props.style) e.style.cssText = props.style;
    for (const c of children) if (c !== null && c !== undefined) e.append(c);
    return e;
  }

  button(text, onclick, primary = false) {
    return this.el("button", {
      textContent: text,
      onclick,
      style:
        "padding:8px 12px;border-radius:8px;border:1px solid var(--divider-color);cursor:pointer;font:inherit;" +
        (primary
          ? "background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)"
          : "background:var(--card-background-color);color:var(--primary-text-color)"),
    });
  }

  /** Datumfält vars innehåll överlever omritning (utkast per nyckel). */
  dateInput(draftKey, value = "") {
    const input = this.el("input", {
      type: "datetime-local",
      value: this._drafts[draftKey] !== undefined ? this._drafts[draftKey] : value,
      style:
        "flex:1;min-width:190px;padding:8px;border-radius:8px;border:1px solid var(--divider-color);" +
        "background:var(--card-background-color);color:var(--primary-text-color);font:inherit",
    });
    input.addEventListener("input", () => { this._drafts[draftKey] = input.value; });
    input.addEventListener("blur", () => {
      if (this._pending) {
        this._pending = false;
        setTimeout(() => this.rerender(), 0);
      }
    });
    return input;
  }

  render() {
    if (!this._hass || !this.config) return;
    this.replaceChildren();
    const ids = this.entities();
    const wrap = this.el("div", { style: "display:grid;gap:12px" });
    this.append(wrap);
    if (!ids.length) {
      const card = this.el("ha-card", { header: this.config.title || "Motorvärmare" });
      card.append(this.el("div", {
        style: "padding:0 16px 16px",
        textContent: this.config.entity
          ? "Entiteten hittades inte. Välj uttag i kortets inställningar."
          : "Inga motorvärmaruttag hittades. Lägg till ett uttag i integrationen Motorvärmare.",
      }));
      wrap.append(card);
      return;
    }
    for (const id of ids) wrap.append(this.renderHeater(id, ids.length === 1));
  }

  renderHeater(entityId, single) {
    const hass = this._hass;
    const st = hass.states[entityId];
    const title = (single && this.config.title) || (st ? mvName(hass, entityId) : "Motorvärmare");
    const card = this.el("ha-card", { header: title });
    const c = this.el("div", { style: "padding:0 16px 16px;display:grid;gap:12px" });
    card.append(c);
    if (!st) {
      c.append("Entiteten hittades inte. Välj uttag i kortets inställningar.");
      return card;
    }
    const a = st.attributes;
    const trips = a.trips || [];
    const call = (service, data) => this.call(entityId, service, data);

    // Status
    const power = mvPowerEntity(hass, a.relay_entity);
    const pst = power ? hass.states[power] : null;
    const color = a.fault ? "var(--error-color)" : a.need ? "var(--warning-color)" : "var(--secondary-text-color)";
    c.append(this.el("div", { style: "display:grid;gap:2px" },
      this.el("div", { textContent: a.status || "", style: `font-weight:600;color:${color}` }),
      this.el("div", {
        style: "font-size:13px;opacity:.75",
        textContent:
          `Uppvärmningstid ${a.heating_minutes} min` +
          (a.temperature !== null && a.temperature !== undefined ? ` vid ${Number(a.temperature).toFixed(1)} °C` : "") +
          (a.temperature_source && a.temperature_source !== "givare" ? ` (${a.temperature_source})` : "") +
          (pst && !["unknown", "unavailable"].includes(pst.state)
            ? ` · effekt ${Math.round(Number(pst.state))} ${pst.attributes.unit_of_measurement || "W"}`
            : "") +
          (a.next_start ? ` · nästa start ${this.fmt(a.next_start)}` : ""),
      }),
    ));
    if (a.test_mode) c.append(this.el("div", { textContent: "TESTLÄGE – uttaget påverkas inte", style: "font-size:13px;font-weight:600" }));

    if (a.fault) {
      c.append(this.el("div", { style: "display:grid;gap:8px;padding:10px;border-radius:8px;border:1px solid var(--error-color)" },
        this.el("div", { textContent: a.fault_reason || "Säkerhetsspärr", style: "color:var(--error-color)" }),
        this.el("div", { textContent: "Kvittering startar inte uttaget. Det startar vid nästa avresa eller vid forcerad start.", style: "font-size:13px;opacity:.75" }),
        this.button("Kvittera spärr", () => call("acknowledge_fault", {}), true),
      ));
    }

    // Ny avresa
    const newKey = `new:${entityId}`;
    const date = this.dateInput(newKey);
    c.append(this.el("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, date,
      this.button("Lägg till avresa", () => {
        if (!date.value) return;
        const d = new Date(date.value);
        if (Number.isNaN(d.getTime())) return;
        delete this._drafts[newKey];
        call("add_departure", { departure_at: d.toISOString() });
      }, true)));

    // Lista
    const list = this.el("div", { style: "display:grid;gap:8px" });
    if (!trips.length) list.append(this.el("div", { textContent: "Inga registrerade avresor", style: "opacity:.7" }));
    for (const t of trips) {
      const row = this.el("div", { style: "display:grid;gap:6px;border-top:1px solid var(--divider-color);padding-top:8px" });
      if (this._editing === t.id) {
        const editKey = `edit:${t.id}`;
        const inp = this.dateInput(editKey, this.local(t.departure_at));
        row.append(this.el("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, inp,
          this.button("Spara", () => {
            const d = new Date(inp.value);
            if (Number.isNaN(d.getTime())) return;
            this._editing = null;
            delete this._drafts[editKey];
            call("edit_departure", { trip_id: t.id, departure_at: d.toISOString() });
          }, true),
          this.button("Avbryt", () => { this._editing = null; delete this._drafts[editKey]; this.rerender(); })));
      } else {
        const isCal = t.source === "calendar";
        const sub = t.skipped
          ? "Överhoppad – ingen uppvärmning"
          : t.started ? `Värmebehov pågår till ${this.fmt(t.end_at, false)}` : `Planerad start ${this.fmt(t.start_at, false)}`;
        const info = this.el("div", { style: t.skipped ? "opacity:.55" : "" },
          this.el("div", {
            textContent: this.fmt(t.departure_at) + (t.label ? ` – ${t.label}` : ""),
            style: "font-weight:500" + (t.skipped ? ";text-decoration:line-through" : ""),
          }),
          this.el("div", {
            style: "font-size:13px;opacity:.75",
            textContent: (isCal ? `Kalender: ${t.calendar || "okänd"} · ` : "") + sub,
          }));
        const actions = this.el("div", { style: "display:flex;gap:6px;flex-wrap:wrap" });
        if (isCal) {
          actions.append(t.skipped
            ? this.button("Återställ", () => call("unskip_departure", { trip_id: t.id }))
            : this.button("Hoppa över", () => call("skip_departure", { trip_id: t.id })));
        } else if (this._confirmDelete === t.id) {
          actions.append(
            this.button("Ja, ta bort", () => { this._confirmDelete = null; call("remove_departure", { trip_id: t.id }); }, true),
            this.button("Avbryt", () => { this._confirmDelete = null; this.rerender(); }));
        } else {
          actions.append(
            this.button("Ändra", () => { this._editing = t.id; this.rerender(); }),
            this.button("Ta bort", () => { this._confirmDelete = t.id; this.rerender(); }));
        }
        row.append(this.el("div", { style: "display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap" }, info, actions));
      }
      list.append(row);
    }
    c.append(list);

    // Forcering
    const sel = this.el("select", { style: "padding:8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);font:inherit" });
    for (const m of [15, 30, 60, 120, 240]) {
      sel.append(this.el("option", { value: m, textContent: m < 60 ? `${m} min` : `${m / 60} h`, selected: m === 60 }));
    }
    const force = this.el("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap;border-top:1px solid var(--divider-color);padding-top:12px" },
      sel, this.button("Forcerad start", () => call("force_start", { minutes: Number(sel.value) })));
    if (a.force_until) {
      force.append(this.button("Stoppa forcering", () => call("stop_force", {})));
      force.append(this.el("span", { textContent: `till ${this.fmt(a.force_until, false)}`, style: "font-size:13px;opacity:.75" }));
    }
    c.append(force);

    if (this._errors[entityId]) c.append(this.el("div", { textContent: this._errors[entityId], style: "color:var(--error-color);font-size:13px" }));
    return card;
  }
}

/** Visuell redigerare: välj alla uttag eller ett visst uttag, och valfri rubrik. */
class MotorvarmareCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this.render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this.render();
  }

  changed(config) {
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  render() {
    if (!this._hass || !this._config) return;
    this.replaceChildren();
    const style = "padding:8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);font:inherit;width:100%;box-sizing:border-box";
    const sel = document.createElement("select");
    sel.style.cssText = style;
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "Alla uttag (nya uttag visas automatiskt)";
    sel.append(all);
    for (const id of mvHeaterEntities(this._hass)) {
      const o = document.createElement("option");
      o.value = id;
      o.textContent = mvName(this._hass, id);
      sel.append(o);
    }
    sel.value = this._config.entity || "";
    sel.onchange = () => {
      const config = { ...this._config };
      if (sel.value) config.entity = sel.value;
      else delete config.entity;
      this.changed(config);
    };
    const title = document.createElement("input");
    title.style.cssText = style;
    title.placeholder = "Rubrik (valfri, bara för ett uttag)";
    title.value = this._config.title || "";
    title.onchange = () => {
      const config = { ...this._config };
      if (title.value.trim()) config.title = title.value.trim();
      else delete config.title;
      this.changed(config);
    };
    const label = (text) => {
      const l = document.createElement("div");
      l.textContent = text;
      l.style.cssText = "font-size:13px;opacity:.75;margin:8px 0 4px";
      return l;
    };
    const box = document.createElement("div");
    box.append(label("Uttag"), sel, label("Rubrik"), title);
    this.append(box);
  }
}

customElements.define("motorvarmare-card", MotorvarmareCard);
customElements.define("motorvarmare-card-editor", MotorvarmareCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "motorvarmare-card",
  name: "Motorvärmare",
  description: "Avresor, forcerad start och säkerhetsstatus. Utan entity visas alla uttag.",
  preview: false,
});
console.info(`motorvarmare-card ${MV_VERSION}`);
