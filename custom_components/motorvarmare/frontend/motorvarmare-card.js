/* Motorvärmare – Lovelace-kort (version 0.4). Inga externa beroenden. */
const MV_VERSION = "0.4.0";

class MotorvarmareCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Ange entity: sensor.<uttag>_avresor");
    this.config = config;
    this._editing = null;
    this._confirmDelete = null;
    this._error = "";
  }

  static getStubConfig(hass) {
    const e = Object.keys(hass.states).find((id) => id.startsWith("sensor.") && hass.states[id].attributes.heater_id);
    return { entity: e || "sensor.motorvarmare_1_avresor" };
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this.config.entity];
    const key = st ? JSON.stringify([st.state, st.attributes]) : "saknas";
    if (key !== this._key) {
      this._key = key;
      this.render();
    }
  }

  getCardSize() {
    return 6;
  }

  async call(service, data) {
    this._error = "";
    try {
      const id = this._hass.states[this.config.entity].attributes.heater_id;
      await this._hass.callService("motorvarmare", service, { heater_id: id, ...data });
    } catch (e) {
      this._error = e.message || String(e);
    }
    this._key = null;
    this.render();
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

  dateInput(value = "") {
    return this.el("input", {
      type: "datetime-local",
      value,
      style:
        "flex:1;min-width:190px;padding:8px;border-radius:8px;border:1px solid var(--divider-color);" +
        "background:var(--card-background-color);color:var(--primary-text-color);font:inherit",
    });
  }

  render() {
    const st = this._hass && this._hass.states[this.config.entity];
    this.replaceChildren();
    const card = this.el("ha-card", { header: this.config.title || (st && st.attributes.friendly_name ? st.attributes.friendly_name.replace(/ Avresor$/, "") : "Motorvärmare") });
    const c = this.el("div", { style: "padding:0 16px 16px;display:grid;gap:12px" });
    card.append(c);
    this.append(card);
    if (!st) {
      c.append("Entiteten hittades inte. Kontrollera entity i kortets inställningar.");
      return;
    }
    const a = st.attributes;
    const trips = a.trips || [];

    // Status
    const color = a.fault ? "var(--error-color)" : a.need ? "var(--warning-color)" : "var(--secondary-text-color)";
    const head = this.el("div", { style: "display:grid;gap:2px" },
      this.el("div", { textContent: a.status || "", style: `font-weight:600;color:${color}` }),
      this.el("div", {
        style: "font-size:13px;opacity:.75",
        textContent:
          `Uppvärmningstid ${a.heating_minutes} min` +
          (a.temperature !== null && a.temperature !== undefined ? ` vid ${Number(a.temperature).toFixed(1)} °C` : "") +
          (a.temperature_source && a.temperature_source !== "givare" ? ` (${a.temperature_source})` : "") +
          (a.next_start ? ` · nästa start ${this.fmt(a.next_start)}` : ""),
      }),
    );
    c.append(head);
    if (a.test_mode) c.append(this.el("div", { textContent: "TESTLÄGE – uttaget påverkas inte", style: "font-size:13px;font-weight:600" }));

    if (a.fault) {
      c.append(this.el("div", { style: "display:grid;gap:8px;padding:10px;border-radius:8px;border:1px solid var(--error-color)" },
        this.el("div", { textContent: a.fault_reason || "Säkerhetsspärr", style: "color:var(--error-color)" }),
        this.el("div", { textContent: "Kvittering startar inte uttaget. Det startar vid nästa avresa eller vid forcerad start.", style: "font-size:13px;opacity:.75" }),
        this.button("Kvittera spärr", () => this.call("acknowledge_fault", {}), true),
      ));
    }

    // Ny avresa
    const date = this.dateInput();
    c.append(this.el("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, date,
      this.button("Lägg till avresa", () => {
        if (!date.value) return;
        const d = new Date(date.value);
        if (!Number.isNaN(d.getTime())) this.call("add_departure", { departure_at: d.toISOString() });
      }, true)));

    // Lista
    const list = this.el("div", { style: "display:grid;gap:8px" });
    if (!trips.length) list.append(this.el("div", { textContent: "Inga registrerade avresor", style: "opacity:.7" }));
    for (const t of trips) {
      const row = this.el("div", { style: "display:grid;gap:6px;border-top:1px solid var(--divider-color);padding-top:8px" });
      if (this._editing === t.id) {
        const inp = this.dateInput(this.local(t.departure_at));
        row.append(this.el("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, inp,
          this.button("Spara", () => {
            const d = new Date(inp.value);
            if (Number.isNaN(d.getTime())) return;
            this._editing = null;
            this.call("edit_departure", { trip_id: t.id, departure_at: d.toISOString() });
          }, true),
          this.button("Avbryt", () => { this._editing = null; this._key = null; this.render(); })));
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
            ? this.button("Återställ", () => this.call("unskip_departure", { trip_id: t.id }))
            : this.button("Hoppa över", () => this.call("skip_departure", { trip_id: t.id })));
        } else if (this._confirmDelete === t.id) {
          actions.append(
            this.button("Ja, ta bort", () => { this._confirmDelete = null; this.call("remove_departure", { trip_id: t.id }); }, true),
            this.button("Avbryt", () => { this._confirmDelete = null; this._key = null; this.render(); }));
        } else {
          actions.append(
            this.button("Ändra", () => { this._editing = t.id; this._key = null; this.render(); }),
            this.button("Ta bort", () => { this._confirmDelete = t.id; this._key = null; this.render(); }));
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
      sel, this.button("Forcerad start", () => this.call("force_start", { minutes: Number(sel.value) })));
    if (a.force_until) {
      force.append(this.button("Stoppa forcering", () => this.call("stop_force", {})));
      force.append(this.el("span", { textContent: `till ${this.fmt(a.force_until, false)}`, style: "font-size:13px;opacity:.75" }));
    }
    c.append(force);

    if (this._error) c.append(this.el("div", { textContent: this._error, style: "color:var(--error-color);font-size:13px" }));
  }
}

customElements.define("motorvarmare-card", MotorvarmareCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "motorvarmare-card", name: "Motorvärmare", description: "Avresor, forcerad start och säkerhetsstatus per uttag" });
console.info(`motorvarmare-card ${MV_VERSION}`);
