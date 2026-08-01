"use strict";

// Telefon icin ince istemci: masaustu uygulamasiyla ayni WebSocket sozlesmesini
// konusur (bkz. docs/PROTOCOL.md). Derleme adimi yok - dosyalar ajan tarafindan
// oldugu gibi sunuluyor, bakimi bir npm zincirine bagli degil.

const TOKEN_KEY = "pi-agent-token";

const state = {
  socket: null,
  token: localStorage.getItem(TOKEN_KEY) || "",
  capabilities: {},
};

const $ = (id) => document.getElementById(id);

// --- bicimleme --------------------------------------------------------------

function bytesHuman(value) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return i === 0 ? `${value} B` : `${value.toFixed(1)} ${units[i]}`;
}

function durationHuman(seconds) {
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days}g ${hours}sa ${minutes}dk`;
  if (hours) return `${hours}sa ${minutes}dk`;
  return `${minutes}dk`;
}

// --- baglanti ---------------------------------------------------------------

function envelope(type, payload) {
  return JSON.stringify({
    type,
    id: (crypto.randomUUID ? crypto.randomUUID() : String(Math.random())).replace(/-/g, ""),
    ts: Date.now() / 1000,
    payload: payload || {},
  });
}

function send(type, payload) {
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    state.socket.send(envelope(type, payload));
  }
}

function setStatus(text, cls) {
  const el = $("status");
  el.textContent = text;
  el.className = "status" + (cls ? " " + cls : "");
}

function connect() {
  // Sayfa ajanin kendisinden geldigi icin adres zaten dogru: kullaniciya IP
  // sordurmaya gerek yok, sadece token gerekiyor.
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws`);
  state.socket = socket;
  setStatus("baglaniliyor…");

  socket.onopen = () => send("auth.request", { token: state.token });

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    handle(message);
  };

  socket.onclose = () => {
    // Masaustu uygulamasiyla ayni tercih: kendiliginden yeniden denemiyoruz,
    // kullanici ne zaman isterse o zaman.
    setStatus("baglanti kesildi — dokunup yeniden dene", "down");
    $("status").onclick = () => connect();
  };

  socket.onerror = () => setStatus("baglanti hatasi", "down");
}

function handle(message) {
  const payload = message.payload || {};
  switch (message.type) {
    case "auth.ok":
      state.capabilities = payload.capabilities || {};
      onAuthenticated();
      break;
    case "auth.rejected":
      showLogin("Token reddedildi.");
      break;
    case "stats.update":
      renderStats(payload);
      break;
    case "docker.list.result":
      renderContainers(payload.containers || []);
      break;
    case "docker.action.result":
      $("docker-status").textContent = payload.ok
        ? `${payload.container} ${payload.action}: tamam`
        : `${payload.container} ${payload.action} basarisiz: ${payload.detail}`;
      if (payload.ok) send("docker.list", { include_stopped: true });
      break;
    case "power.action.result":
      $("power-status").textContent = payload.ok
        ? `${payload.action}: ${payload.detail}. Baglantinin kesilmesi normaldir.`
        : `${payload.action} basarisiz: ${payload.detail}`;
      break;
    case "error":
      showError(payload.code, payload.message);
      break;
  }
}

function onAuthenticated() {
  localStorage.setItem(TOKEN_KEY, state.token);
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  setStatus("bagli", "ok");
  $("status").onclick = null;

  const docker = state.capabilities.docker;
  $("docker-refresh").disabled = !docker;
  if (docker) {
    send("docker.list", { include_stopped: true });
  } else {
    $("docker-status").textContent =
      state.capabilities.docker_detail || "Docker kullanilamiyor";
  }

  const systemd = state.capabilities.systemd;
  $("reboot").disabled = !systemd;
  $("shutdown").disabled = !systemd;
  if (!systemd) $("power-status").textContent = "systemd yok — guc kontrolu kapali";
}

function showError(code, message) {
  const target = currentTab() === "docker" ? $("docker-status") : $("power-status");
  target.textContent = `${code}: ${message}`;
}

function showLogin(error) {
  $("app").classList.add("hidden");
  $("login").classList.remove("hidden");
  $("login-error").textContent = error || "";
  $("login-button").disabled = false;
}

// --- ekranlar ---------------------------------------------------------------

function renderStats(stats) {
  $("host").textContent = stats.hostname;
  $("cpu").textContent = `${stats.cpu.percent.toFixed(0)} %`;
  $("cpu-sub").textContent = `${stats.cpu.per_core.length} cekirdek` +
    (stats.cpu.frequency_mhz ? ` · ${Math.round(stats.cpu.frequency_mhz)} MHz` : "");

  if (stats.cpu.temperature_c === null || stats.cpu.temperature_c === undefined) {
    $("temp").textContent = "—";
    $("temp-sub").textContent = "sensor okunamadi";
  } else {
    $("temp").textContent = `${stats.cpu.temperature_c.toFixed(1)} °C`;
    $("temp-sub").textContent = "throttle ~85 °C";
  }

  $("mem").textContent = `${stats.memory.percent.toFixed(0)} %`;
  $("mem-sub").textContent =
    `${bytesHuman(stats.memory.used_bytes)} / ${bytesHuman(stats.memory.total_bytes)}`;

  const root = stats.disks.find((d) => d.mountpoint === "/") || stats.disks[0];
  if (root) {
    $("disk").textContent = `${root.percent.toFixed(0)} %`;
    $("disk-sub").textContent =
      `${bytesHuman(root.used_bytes)} / ${bytesHuman(root.total_bytes)}`;
  }

  const load = stats.load_avg ? ` · yuk ${stats.load_avg.map((v) => v.toFixed(2)).join(", ")}` : "";
  $("uptime").textContent = `calisma suresi ${durationHuman(stats.uptime_seconds)}${load}`;
}

function renderContainers(containers) {
  const list = $("containers");
  list.textContent = "";

  containers.forEach((container) => {
    const item = document.createElement("li");

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = container.name;

    const meta = document.createElement("div");
    meta.className = "meta";
    const stateSpan = document.createElement("span");
    stateSpan.className = "state-" + container.state;
    stateSpan.textContent = container.state;
    meta.append(stateSpan, document.createTextNode(` · ${container.image}`));
    if (container.ports) meta.append(document.createTextNode(` · ${container.ports}`));

    const actions = document.createElement("div");
    actions.className = "actions";
    const running = container.state === "running";
    [
      ["Baslat", "start", !running],
      ["Durdur", "stop", running],
      ["Yeniden", "restart", running],
    ].forEach(([label, action, enabled]) => {
      const button = document.createElement("button");
      button.textContent = label;
      button.disabled = !enabled;
      button.onclick = () => {
        $("docker-status").textContent = `${container.name}: ${action}…`;
        send("docker.action", { container: container.name, action });
      };
      actions.append(button);
    });

    item.append(name, meta, actions);
    list.append(item);
  });

  const running = containers.filter((c) => c.state === "running").length;
  $("docker-status").textContent = `${containers.length} container · ${running} calisiyor`;
}

// --- sekmeler ve olaylar ----------------------------------------------------

function currentTab() {
  const active = document.querySelector("nav button.active");
  return active ? active.dataset.tab : "dashboard";
}

document.querySelectorAll("nav button").forEach((button) => {
  button.onclick = () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.add("hidden"));
    $("tab-" + button.dataset.tab).classList.remove("hidden");
    if (button.dataset.tab === "docker" && state.capabilities.docker) {
      send("docker.list", { include_stopped: true });
    }
  };
});

$("login-button").onclick = () => {
  state.token = $("token").value.trim();
  if (!state.token) return;
  $("login-button").disabled = true;
  $("login-error").textContent = "";
  connect();
};

$("token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("login-button").click();
});

$("docker-refresh").onclick = () => send("docker.list", { include_stopped: true });

function confirmPower(action, question) {
  if (!confirm(question)) return;
  $("power-status").textContent = "komut gonderiliyor…";
  send("power.action", { action });
}

$("reboot").onclick = () =>
  confirmPower("reboot", "Pi yeniden baslatilsin mi? Baglanti kesilecek.");

$("shutdown").onclick = () =>
  confirmPower(
    "shutdown",
    "Pi kapatilsin mi?\n\nUzaktan geri acilamaz: kart uzerindeki guc dugmesine basmaniz gerekir."
  );

// Token daha once kaydedildiyse dogrudan bagla.
if (state.token) {
  $("token").value = state.token;
  connect();
}
