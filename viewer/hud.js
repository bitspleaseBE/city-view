/**
 * GTA-style HUD without the weapons: in-game clock + wallet top-right, a notification feed
 * above the radar, a speedometer while riding, a controls card (H) and a stats panel kept out
 * of the way until you ask for it (F3 / backquote).
 *
 * Existing viewer code keeps writing plain text into #status; every change there becomes a
 * notification, so call sites don't need to know about the HUD.
 */

const CSS = `
.hud-font { font-family: "Helvetica Neue", Arial, sans-serif; color: #fff;
  text-shadow: 0 0 2px #000, 0 1px 2px #000, 0 0 6px rgba(0,0,0,0.55); }
#hud-tr { position: fixed; top: 18px; right: 24px; text-align: right; z-index: 600; pointer-events: none; }
#hud-clock { font-weight: 700; font-size: 2.1rem; line-height: 1; letter-spacing: 0.02em; font-variant-numeric: tabular-nums; }
#hud-day { font-weight: 600; font-size: 0.78rem; letter-spacing: 0.16em; text-transform: uppercase; opacity: 0.85; margin-top: 4px; }
#hud-wallet { font-weight: 700; font-size: 1.45rem; color: #8fe08c; margin-top: 6px; font-variant-numeric: tabular-nums; transition: color .3s; }
#hud-wallet.spent { color: #ff8f7a; }
#hud-wallet.earned { color: #d4ffc4; text-shadow: 0 0 2px #000, 0 0 10px rgba(120,255,120,0.9); }
#hud-health { width: 150px; height: 8px; margin: 8px 0 0 auto; background: rgba(0,0,0,0.55); border-radius: 3px;
  overflow: hidden; opacity: 0; transition: opacity .6s; }
#hud-health.on { opacity: 1; }
#hud-health i { display: block; height: 100%; width: 100%; background: #e04a3a; transition: width .25s; }
#hud-feed { position: fixed; left: 22px; bottom: 196px; width: 248px; z-index: 600; pointer-events: none;
  display: flex; flex-direction: column-reverse; gap: 6px; }
.hud-note { background: rgba(10,12,16,0.78); color: #f2f2f2; font: 500 0.86rem/1.35 "Helvetica Neue", Arial, sans-serif;
  padding: 9px 12px; border-left: 3px solid #ffd800; border-radius: 3px; opacity: 0; transform: translateX(-8px);
  transition: opacity .25s ease, transform .25s ease; }
.hud-note.in { opacity: 1; transform: none; }
#hud-speed { position: fixed; right: 28px; bottom: 100px; text-align: right; z-index: 600; pointer-events: none; display: none; }
#hud-speed .v { font-weight: 800; font-size: 3rem; line-height: 0.95; font-variant-numeric: tabular-nums; }
#hud-speed .u { font-weight: 700; font-size: 0.9rem; letter-spacing: 0.14em; margin-left: 4px; }
#hud-speed .bar { width: 150px; height: 6px; margin: 8px 0 0 auto; background: rgba(0,0,0,0.55); border-radius: 3px; overflow: hidden; }
#hud-speed .bar i { display: block; height: 100%; background: #36d07a; }
#hud-speed .sub { font-weight: 600; font-size: 0.8rem; letter-spacing: 0.06em; margin-top: 5px; opacity: 0.9; }
#hud-help { position: fixed; left: 22px; top: 18px; z-index: 650; pointer-events: none; background: rgba(10,12,16,0.8);
  color: #eee; font: 500 0.84rem/1.6 "Helvetica Neue", Arial, sans-serif; padding: 12px 16px; border-radius: 4px;
  opacity: 0; transition: opacity .35s ease; max-width: 20rem; }
#hud-help.on { opacity: 1; }
#hud-help kbd, #prompt kbd { display: inline-block; min-width: 1.3em; padding: 0 5px; margin-right: 6px; text-align: center;
  background: #f2f2f2; color: #111; border-radius: 3px; font: 700 0.78rem/1.45 "Helvetica Neue", Arial, sans-serif; text-shadow: none; }
#hud-stats { position: fixed; left: 22px; top: 18px; z-index: 640; display: none; pointer-events: none;
  background: rgba(0,0,0,0.62); color: #cfe9d0; font: 12px/1.5 ui-monospace, Menlo, monospace; padding: 8px 10px; border-radius: 4px; white-space: pre; }
#hud-stats.on { display: block; }
`;

const DAYS = ["zondag", "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag"];

export function createHud(opts = {}) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  const el = (tag, id, cls, parent = document.body) => {
    const e = document.createElement(tag);
    if (id) e.id = id;
    if (cls) e.className = cls;
    parent.appendChild(e);
    return e;
  };
  const tr = el("div", "hud-tr", "hud-font");
  const clock = el("div", "hud-clock", "", tr);
  const day = el("div", "hud-day", "", tr);
  const wallet = el("div", "hud-wallet", "", tr);
  const healthBar = el("div", "hud-health", "", tr);
  const healthFill = el("i", "", "", healthBar);
  const feed = el("div", "hud-feed");
  const speed = el("div", "hud-speed", "hud-font");
  speed.innerHTML = '<span class="v">0</span><span class="u">KM/U</span><div class="bar"><i></i></div><div class="sub"></div>';
  const speedV = speed.querySelector(".v");
  const speedBar = speed.querySelector(".bar");
  const speedFill = speed.querySelector(".bar i");
  const speedSub = speed.querySelector(".sub");
  const help = el("div", "hud-help");
  help.innerHTML = [
    "<kbd>W A S D</kbd>lopen · sturen op step/fiets",
    "<kbd>Shift</kbd>rennen · <kbd>Spatie</kbd>springen",
    "<kbd>E</kbd>step · tram · bus · Velo",
    "<kbd>N</kbd>naar avond / ochtend",
    "<kbd>V</kbd>kaart · <kbd>M</kbd>radar",
    "<kbd>Esc</kbd>muis loslaten",
    "<kbd>H</kbd>dit overzicht · <kbd>F3</kbd>tech",
  ].join("<br>");
  const stats = el("div", "hud-stats");

  let money = opts.wallet ?? 25;
  const fmtMoney = (v) => `€${v.toFixed(2)}`;
  wallet.textContent = fmtMoney(money);

  function notify(text, ms = 4200) {
    if (!text) return;
    const n = document.createElement("div");
    n.className = "hud-note";
    n.textContent = text;
    feed.prepend(n);
    while (feed.children.length > 3) feed.lastElementChild.remove();
    requestAnimationFrame(() => n.classList.add("in"));
    setTimeout(() => {
      n.classList.remove("in");
      setTimeout(() => n.remove(), 300);
    }, ms);
  }

  // Mirror #status into the feed (dedupe repeats; the first line is the load-time census).
  const statusEl = document.getElementById("status");
  let lastStatus = "";
  let census = "";
  if (statusEl) {
    new MutationObserver(() => {
      const t = statusEl.textContent.trim();
      if (!t || t === lastStatus) return;
      lastStatus = t;
      if (/^(Walking|Lopen|Free view|Kaart|Loading|Laden)/.test(t)) return; // mode chatter, not news
      if (/\d+ (cars|auto|people|mensen)/.test(t)) {
        census = t;
        return;
      }
      notify(t);
    }).observe(statusEl, { childList: true, characterData: true, subtree: true });
  }

  let helpTimer = 0;
  const setHelp = (on) => {
    help.classList.toggle("on", on);
    document.body.classList.toggle("help-on", on || stats.classList.contains("on"));
  };
  function showHelp(ms = 7000) {
    setHelp(true);
    clearTimeout(helpTimer);
    if (ms) helpTimer = setTimeout(() => setHelp(false), ms);
  }
  function toggleHelp() {
    if (help.classList.contains("on")) setHelp(false);
    else showHelp(0);
  }
  function toggleStats() {
    stats.classList.toggle("on");
    setHelp(false);
  }

  let fpsAcc = 0;
  let fpsN = 0;
  let fps = 0;
  let statsClock = 0;
  /**
   * Per frame. info = { hour, dayIndex, riding: null | { speedKmh, battery, sub },
   *                     stats: () => object }
   */
  function update(dt, info) {
    const h = ((info.hour % 24) + 24) % 24;
    const hh = Math.floor(h);
    const mm = Math.floor((h - hh) * 60);
    const t = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
    if (clock.textContent !== t) clock.textContent = t;
    const d = DAYS[(info.dayIndex ?? 5) % 7];
    if (day.textContent !== d) day.textContent = d;

    const r = info.riding;
    speed.style.display = r ? "block" : "none";
    if (r) {
      speedV.textContent = String(Math.round(r.speedKmh));
      speedBar.style.display = r.battery == null ? "none" : "block";
      if (r.battery != null) {
        speedFill.style.width = `${Math.max(0, Math.min(100, r.battery))}%`;
        speedFill.style.background = r.battery < 20 ? "#ff6b4a" : "#36d07a";
      }
      speedSub.textContent = r.sub || "";
    }

    fpsAcc += dt;
    fpsN++;
    if (fpsAcc >= 0.5) {
      fps = fpsN / fpsAcc;
      fpsAcc = 0;
      fpsN = 0;
    }
    if (stats.classList.contains("on") && (statsClock -= dt) <= 0) {
      statsClock = 0.25;
      const s = info.stats ? info.stats() : {};
      const lines = [`fps      ${fps.toFixed(0)}`];
      for (const [k, v] of Object.entries(s)) lines.push(`${k.padEnd(8)} ${v}`);
      if (census) lines.push("", census.replace(/ · /g, "\n"));
      stats.textContent = lines.join("\n");
    }
  }

  function spend(amount, label) {
    money = Math.max(0, money - amount);
    wallet.textContent = fmtMoney(money);
    wallet.classList.add("spent");
    setTimeout(() => wallet.classList.remove("spent"), 900);
    if (label) notify(`${label} · −${fmtMoney(amount)}`);
  }

  function earn(amount, label) {
    money += amount;
    wallet.textContent = fmtMoney(money);
    wallet.classList.remove("spent");
    wallet.classList.add("earned");
    setTimeout(() => wallet.classList.remove("earned"), 900);
    if (label) notify(`${label} · +${fmtMoney(amount)}`);
  }

  let shownHealth = -1;
  /** 0–100; the bar shows only while you're hurt. */
  function setHealth(v) {
    const h = Math.round(v);
    if (h === shownHealth) return;
    shownHealth = h;
    healthFill.style.width = `${h}%`;
    healthBar.classList.toggle("on", h < 100);
  }

  return {
    update,
    notify,
    spend,
    earn,
    setHealth,
    showHelp,
    toggleHelp,
    toggleStats,
    get money() {
      return money;
    },
  };
}
