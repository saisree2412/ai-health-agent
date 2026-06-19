// Tiny vanilla-JS frontend. No framework, no build step.

const $ = (sel) => document.querySelector(sel);

const chatLog = $("#chat-log");
const chatForm = $("#chat-form");
const chatInput = $("#chat-input");
const sendBtn = chatForm.querySelector("button");

// Daily targets used to draw progress bars in the sidebar.
// Macro targets are generic; micros use RDA for adult women 19-50.
// (In a real app these'd be derived from the user's Profile + Goals.)
const MACRO_TARGETS = {
  calories: 1800,
  sodium_mg: 2000,
  protein_g: 80,
  fiber_g: 30,
  sugar_g: 25,           // added-sugar goal in seed
  saturated_fat_g: 22,
};

const MICRO_TARGETS = {
  // [target, unit, hover-explanation]
  iron_mg:         [18,   "mg",  "RDA for menstruating women. Critical for energy."],
  calcium_mg:      [1000, "mg",  "Bone health."],
  magnesium_mg:    [310,  "mg",  "PMS / sleep / muscle recovery."],
  zinc_mg:         [8,    "mg",  "Skin (acne), immune, hormone balance."],
  vitamin_d_iu:    [600,  "IU",  "Often supplemented. Sunlight + fortified foods."],
  folate_mcg:      [400,  "mcg", "Reproductive health."],
  vitamin_b12_mcg: [2.4,  "mcg", "Energy, mood. Mostly animal foods or fortified."],
  vitamin_c_mg:    [75,   "mg",  "Boosts non-heme iron absorption."],
  omega3_g:        [1.1,  "g",   "Anti-inflammatory. ALA + EPA + DHA."],
  potassium_mg:    [2600, "mg",  "Electrolyte balance. Fruits, veg, beans."],
};

function chip(text, tooltip) {
  const t = tooltip ? ` title="${escape(tooltip)}"` : "";
  return `<span class="chip"${t}>${escape(text)}</span>`;
}

// Truncate a string to N chars at a word boundary.
function shorten(s, n = 32) {
  if (!s) return "";
  if (s.length <= n) return s;
  const slice = s.slice(0, n);
  const cut = slice.lastIndexOf(" ");
  return (cut > n / 2 ? slice.slice(0, cut) : slice) + "…";
}

function escape(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadProfile() {
  const r = await fetch("/api/profile").then((r) => r.json());
  const el = $("#profile-content");
  if (!r.profile) {
    el.innerHTML = `<div class="loading">no profile yet — run <code>health-agent seed</code></div>`;
    return;
  }
  const p = r.profile;
  const dob = new Date(p.date_of_birth);
  const age = Math.floor((Date.now() - dob.getTime()) / (365.25 * 24 * 3600 * 1000));

  let html = "";
  html += `<div class="kv"><span class="label">name</span><span class="value">${escape(p.name)}</span></div>`;
  html += `<div class="kv"><span class="label">age · sex</span><span class="value">${age} · ${escape(p.sex)}</span></div>`;
  html += `<div class="kv"><span class="label">activity</span><span class="value">${escape(p.activity_level)}</span></div>`;

  if (r.conditions.length) {
    html += `<h3>Conditions</h3>`;
    html += r.conditions
      .map((c) => chip(`${c.name} (${c.severity})`, c.notes || c.name))
      .join("");
  }
  if (r.allergies.length) {
    html += `<h3>Allergies</h3>`;
    html += r.allergies
      .map((a) => chip(`${a.allergen} · ${a.severity}`, a.reaction || a.allergen))
      .join("");
  }
  if (r.medications.length) {
    html += `<h3>Meds</h3>`;
    html += r.medications
      .map((m) => chip(`${m.name} ${m.dose}${m.unit}`, `${m.frequency}${m.indication ? " — " + m.indication : ""}`))
      .join("");
  }
  if (r.goals.length) {
    html += `<h3>Goals</h3>`;
    html += r.goals
      .map((g) => {
        // For "other" goals, the kind name is uninformative — use the notes.
        let label;
        if (g.kind === "other") {
          label = shorten(g.notes || "other", 36);
        } else {
          const target = g.target_value ? ` → ${g.target_value}${g.target_unit || ""}` : "";
          label = `${g.kind}${target}`;
        }
        return chip(label, g.notes || g.kind);
      })
      .join("");
  }
  if (r.supplements.length) {
    html += `<h3>Supplements</h3>`;
    html += r.supplements
      .map((s) => chip(
        `${s.name} ${s.typical_dose}${s.typical_unit}`,
        s.interaction_tags && s.interaction_tags.length
          ? `interactions: ${s.interaction_tags.join(", ")}`
          : s.name
      ))
      .join("");
  }
  el.innerHTML = html;
}

function macroBar(label, value, target, unit, opts = {}) {
  const pct = Math.min(100, (value / target) * 100);
  const over = value > target;
  // For "limit" macros (sodium, sugar, saturated fat) over is BAD.
  // For "target" macros (protein, fiber, micros) over is GOOD.
  const overColor = opts.isLimit ? " over" : "";
  const tip = opts.tooltip ? ` title="${escape(opts.tooltip)}"` : "";
  const valueText = value < 10 ? value.toFixed(1) : value.toFixed(0);
  return `
    <div class="macro-bar"${tip}>
      <div class="row">
        <span class="label">${escape(label)}</span>
        <span class="value">${valueText} / ${target} ${unit}</span>
      </div>
      <div class="bar"><div class="bar-fill${over ? overColor : ""}" style="width:${pct}%"></div></div>
    </div>`;
}

async function loadToday() {
  const r = await fetch("/api/today").then((r) => r.json());
  const t = r.totals;
  let html = "";

  // ── Macros ────────────────────────────────────────────────────────
  html += macroBar("Calories", t.calories, MACRO_TARGETS.calories, "kcal");
  html += macroBar("Protein", t.protein_g, MACRO_TARGETS.protein_g, "g");
  html += macroBar("Fiber", t.fiber_g, MACRO_TARGETS.fiber_g, "g");
  html += macroBar("Sodium", t.sodium_mg, MACRO_TARGETS.sodium_mg, "mg", { isLimit: true });
  html += macroBar("Added sugar", t.sugar_g, MACRO_TARGETS.sugar_g, "g", {
    isLimit: true,
    tooltip: "Your goal: ≤ 25g added sugar/day for skin + hormones.",
  });
  html += macroBar("Saturated fat", t.saturated_fat_g, MACRO_TARGETS.saturated_fat_g, "g", { isLimit: true });

  html += `<div class="kv" style="margin-top:10px;"><span class="label">meals logged</span><span class="value">${r.meals.length}</span></div>`;
  html += `<div class="kv"><span class="label">supplements taken</span><span class="value">${r.supplements.length}</span></div>`;

  $("#today-content").innerHTML = html;

  // ── Micros (separate section) ─────────────────────────────────────
  let microHtml = "";
  // Order tuned for what matters to a 28F with irregular periods + acne.
  const microOrder = [
    "iron_mg",
    "calcium_mg",
    "magnesium_mg",
    "zinc_mg",
    "vitamin_d_iu",
    "omega3_g",
    "folate_mcg",
    "vitamin_b12_mcg",
    "vitamin_c_mg",
    "potassium_mg",
  ];
  const labels = {
    iron_mg: "Iron",
    calcium_mg: "Calcium",
    magnesium_mg: "Magnesium",
    zinc_mg: "Zinc",
    vitamin_d_iu: "Vitamin D",
    omega3_g: "Omega-3",
    folate_mcg: "Folate",
    vitamin_b12_mcg: "Vitamin B12",
    vitamin_c_mg: "Vitamin C",
    potassium_mg: "Potassium",
  };

  for (const key of microOrder) {
    const [target, unit, tip] = MICRO_TARGETS[key];
    microHtml += macroBar(labels[key], t[key] ?? 0, target, unit, { tooltip: tip });
  }
  $("#micros-content").innerHTML = microHtml;
}

async function loadMeals() {
  const meals = await fetch("/api/meals?limit=5").then((r) => r.json());
  const el = $("#meals-content");
  if (!meals.length) {
    el.innerHTML = `<div class="loading">no meals logged yet</div>`;
    return;
  }
  el.innerHTML = meals
    .map((m) => {
      const t = new Date(m.eaten_at);
      const time = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return `
        <div class="meal-row">
          <div class="desc">
            <strong>${escape(m.food_name)}</strong> · ${m.servings}×
            <div class="meta">${escape(m.slot)} @ ${time} · ${m.macros.calories.toFixed(0)} kcal · ${m.macros.sodium_mg.toFixed(0)} mg Na</div>
          </div>
          <button class="delete-btn" data-id="${m.id}" title="delete">✕</button>
        </div>`;
    })
    .join("");

  el.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this meal entry?")) return;
      const id = btn.dataset.id;
      await fetch(`/api/meals/${id}`, { method: "DELETE" });
      await refresh();
    });
  });
}

async function refresh() {
  await Promise.all([loadProfile(), loadToday(), loadMeals()]);
}

function appendMessage(role, text, recommendations = [], warnings = []) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  let inner = `<div class="role">${role}</div><div class="body">${escape(text)}`;
  recommendations.forEach((rec) => {
    inner += `<div class="rec">${escape(rec.text)}<div class="rationale">${escape(rec.rationale)}</div><div class="rtype">${escape(rec.reasoning_type)}</div></div>`;
  });
  warnings.forEach((w) => {
    inner += `<div class="warn">⚠ ${escape(w)}</div>`;
  });
  inner += `</div>`;

  wrap.innerHTML = inner;
  chatLog.appendChild(wrap);
  chatLog.scrollTop = chatLog.scrollHeight;
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  appendMessage("user", text);
  chatInput.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "…";

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      appendMessage("agent", `Error: ${data.detail || resp.status}`);
    } else if (!data.reply) {
      appendMessage("agent", "No reply — executor or verifier failed. Check the server logs.");
    } else {
      const r = data.reply;
      if (r.action === "suggest") {
        appendMessage("agent", r.message, r.recommendations || [], r.warnings || []);
      } else if (r.action === "ask") {
        appendMessage("agent", r.question, [], [r.why_needed]);
      } else if (r.action === "confirm") {
        const text = r.what_was_done + (r.summary ? "\n\n" + r.summary : "");
        appendMessage("agent", text);
      } else {
        appendMessage("agent", JSON.stringify(r));
      }
    }
    await refresh();
  } catch (err) {
    appendMessage("agent", `Error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send";
    chatInput.focus();
  }
});

refresh();
chatInput.focus();
