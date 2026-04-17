const $ = (id) => document.getElementById(id);

const COLOR_CLASSIFY = {
  red: "HOSTILE",
  red2: "HOSTILE",
  yellow: "CAUTION",
  green: "FRIENDLY",
  blue: "UNKNOWN",
};

const MAX_LOG = 30;

const state = {
  brainUrl: "",
  streamUrl: "",
  token: "",
  mode: "manual",
  color: "red",
  joyX: 0,
  joyY: 0,
  pollTimer: null,
  driveTimer: null,
  clockTimer: null,
  sessionStart: Date.now(),
  link: "offline",
  lastStatus: null,
  lastStatusMs: 0,
  missedPolls: 0,
  voiceOn: true,
  speaking: false,
  lastSpoken: 0,
  lastSpokenText: "",
  prevHasTarget: false,
  prevTargetCount: 0,
  prevMode: "manual",
  prevSearchState: "idle",
  prevShadowState: "idle",
  settingsOpen: true,
  log: [],
  ws: null,
  tuneDebounce: null,
  pollInFlight: false,
  driveInFlight: false,
  driveAbort: null,
  servoInFlight: false,
  servoDebounce: null,
  prevScene: "",
};

const saved = JSON.parse(localStorage.getItem("sentinel") || "{}");
if (saved.brainUrl)  $("brainUrl").value  = saved.brainUrl;
if (saved.streamUrl) $("streamUrl").value = saved.streamUrl;
if (saved.token)     $("brainToken").value = saved.token;
if (typeof saved.voiceOn === "boolean") state.voiceOn = saved.voiceOn;
state.token = saved.token || "";
updateVoiceIcon();

// Pre-fill the brain URL with the current origin. If the UI is served
// from the brain itself, probing /api/health confirms it and we auto-connect.
if (!$("brainUrl").value && (location.protocol === "http:" || location.protocol === "https:")) {
  $("brainUrl").value = location.origin;
}

let autoConnect = !!saved.brainUrl;
$("settingsPanel").hidden = autoConnect;
if (!autoConnect) {
  fetch(`${location.origin}/api/health`, { cache: "no-store" })
    .then((r) => r.ok ? r.json() : null)
    .then((j) => {
      if (j && j.ok) {
        $("brainUrl").value = location.origin;
        connect();
      }
    })
    .catch(() => {});
}
$("connectBtn").addEventListener("click", connect);
$("stopBtn").addEventListener("click", halt);
$("settingsBtn").addEventListener("click", toggleSettings);
$("voiceBtn").addEventListener("click", toggleVoice);

document.querySelectorAll("#modeSwitch button").forEach((b) => {
  b.addEventListener("click", () => setMode(b.dataset.mode));
});
document.querySelectorAll("#colorRow button").forEach((b) => {
  b.addEventListener("click", () => setColor(b.dataset.color));
});

setupJoystick($("joy"), $("joyStick"), (x, y) => {
  state.joyX = x;
  state.joyY = y;
  $("driveMeta").textContent = driveMetaText();
});

// Servo slider events
["pan", "tilt"].forEach((key) => {
  const sl = $(key + "Slider");
  if (!sl) return;
  sl.addEventListener("input", () => {
    $(key + "Val").textContent = sl.value;
    $("servoMeta").textContent = `PAN ${$("panSlider").value} \u00b7 TILT ${$("tiltSlider").value}`;
    debounceServo();
  });
});
if ($("servoCenterBtn")) {
  $("servoCenterBtn").addEventListener("click", centerServo);
}

if ($("sceneNarrateBtn")) {
  $("sceneNarrateBtn").addEventListener("click", () => {
    const text = $("sceneText")?.textContent;
    if (text && text !== "Awaiting visual feed...") narrate(text, { force: true });
  });
}

// (tabs removed – panels are always visible around the center feed)

["kp", "ki", "kd", "speed", "area"].forEach((key) => {
  const sl = $(key + "Slider");
  if (!sl) return;
  sl.addEventListener("input", () => {
    $(key + "Val").textContent = sl.value;
    debounceTune();
  });
});

const overlay = $("overlay");
const octx = overlay.getContext("2d");
const videoImg = $("videoImg");
const videoFrame = $("videoFrame");
videoImg.addEventListener("load", resizeOverlay);
window.addEventListener("resize", resizeOverlay);

// Click on video to select target
overlay.style.pointerEvents = "auto";
overlay.addEventListener("click", (e) => {
  if (!state.brainUrl) return;
  const s = state.lastStatus;
  if (!s || !s.frame_w || !s.frame_h) return;
  const rect = videoFrame.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const dw = overlay.width / dpr;
  const dh = overlay.height / dpr;
  const srcW = s.frame_w, srcH = s.frame_h;
  const scale = Math.min(dw / srcW, dh / srcH);
  const drawW = srcW * scale, drawH = srcH * scale;
  const offX = (dw - drawW) / 2, offY = (dh - drawH) / 2;
  const clickX = e.clientX - rect.left;
  const clickY = e.clientY - rect.top;
  const frameX = Math.round((clickX - offX) / scale);
  const frameY = Math.round((clickY - offY) / scale);
  if (frameX < 0 || frameY < 0 || frameX > srcW || frameY > srcH) return;
  brainFetch(`/select_target`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ x: frameX, y: frameY }),
  }).catch(() => {});
  logEvent("info", "TARGET", `Manual select at (${frameX}, ${frameY})`);
  narrate("Target designated");
});

state.clockTimer = setInterval(updateClock, 500);
updateClock();
logEvent("info", "BOOT", "Sentinel console online");

// Auto-connect on load if URLs are saved
if (autoConnect) {
  setTimeout(connect, 300);
}

function updateClock() {
  const ms = Date.now() - state.sessionStart;
  const s = Math.floor(ms / 1000);
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  $("missionClock").textContent = `${h}:${m}:${sec}`;
}

function toggleSettings() {
  state.settingsOpen = !state.settingsOpen;
  $("settingsPanel").hidden = !state.settingsOpen;
  $("settingsBtn").classList.toggle("active", state.settingsOpen);
}

function toggleVoice() {
  state.voiceOn = !state.voiceOn;
  persistSettings();
  updateVoiceIcon();
  if (!state.voiceOn && window.speechSynthesis) window.speechSynthesis.cancel();
  logEvent("info", "COMMS", state.voiceOn ? "Narration enabled" : "Narration muted");
}

function updateVoiceIcon() {
  $("voiceIconOn").hidden  = !state.voiceOn;
  $("voiceIconOff").hidden =  state.voiceOn;
  $("voiceBtn").classList.toggle("active", state.voiceOn);
}

function persistSettings() {
  localStorage.setItem("sentinel", JSON.stringify({
    brainUrl:  state.brainUrl || $("brainUrl").value,
    streamUrl: state.streamUrl || $("streamUrl").value,
    token:     state.token || $("brainToken").value,
    voiceOn:   state.voiceOn,
  }));
}

function authHeaders() {
  return state.token ? { "X-Brain-Token": state.token } : {};
}

function brainFetch(path, init = {}) {
  const base = state.brainUrl || "";
  const url = path.startsWith("http") ? path : `${base}${path}`;
  const headers = { ...(init.headers || {}), ...authHeaders() };
  return fetch(url, { ...init, headers });
}

function resolveStreamUrl(raw) {
  if (!raw) return state.brainUrl ? `${state.brainUrl}/stream` : "";
  if (raw.startsWith("/") && state.brainUrl) return `${state.brainUrl}${raw}`;
  const pageIsHttps = location.protocol === "https:";
  if (pageIsHttps && raw.startsWith("http://") && state.brainUrl) {
    return `${state.brainUrl}/stream`;
  }
  return raw;
}

function startStream(url) {
  const resolved = resolveStreamUrl(url);
  if (!resolved || videoImg.src === resolved) return;
  state.streamUrl = resolved;
  $("streamUrl").value = resolved;
  videoImg.src = resolved;
  videoImg.classList.add("live");
  $("noSignal").hidden = true;
  videoImg.onerror = () => {
    videoImg.classList.remove("live");
    $("noSignal").hidden = false;
  };
  persistSettings();
  logEvent("info", "VIDEO", `Stream: ${resolved}`);
}

function connect() {
  state.brainUrl  = $("brainUrl").value.trim().replace(/\/$/, "");
  state.token     = $("brainToken").value.trim();
  const manualStream = $("streamUrl").value.trim();
  if (manualStream) startStream(manualStream);
  else startStream("");
  persistSettings();

  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollStatus, 400);
  clearInterval(state.driveTimer);
  state.driveTimer = setInterval(driveTick, 100);

  logEvent("info", "UPLINK", `Connecting to ${state.brainUrl}`);
  narrate("Establishing uplink");
  pollStatus();
  connectWS();
  fetchTune();

  if (state.settingsOpen) toggleSettings();
}

async function pollStatus() {
  if (!state.brainUrl) return;
  if (state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    const r = await brainFetch(`/status`, { cache: "no-store" });
    if (!r.ok) throw new Error("bad status");
    const s = await r.json();
    state.lastStatus = s;
    state.lastStatusMs = Date.now();
    state.missedPolls = 0;

    if (state.link !== "online") {
      state.link = "online";
      setLinkPill("online");
      logEvent("info", "UPLINK", "Link established");
      narrate("Link established");
    }
    // Auto-load camera stream from brain if not already streaming
    if (s.stream_url && !state.streamUrl) {
      startStream(s.stream_url);
      narrate("Camera feed acquired");
    }
    applyStatus(s);
  } catch (_) {
    state.missedPolls++;
    if (state.link === "online" && state.missedPolls >= 3) {
      state.link = "offline";
      setLinkPill("offline");
      logEvent("alert", "UPLINK", "Link lost");
      narrate("Link down");
    } else if (state.link === "online") {
      setLinkPill("poor");
    }
  } finally {
    state.pollInFlight = false;
  }
}

function setLinkPill(kind) {
  const pill = $("linkPill");
  pill.classList.remove("offline", "poor");
  const label = pill.querySelector(".label");
  if (kind === "online") { label.textContent = "LINK"; }
  else if (kind === "poor") { pill.classList.add("poor"); label.textContent = "POOR"; }
  else { pill.classList.add("offline"); label.textContent = "OFFLINE"; }

  const sig = $("signalVal");
  sig.classList.remove("offline", "strong");
  if (kind === "online") { sig.textContent = "STRONG"; sig.classList.add("strong"); }
  else if (kind === "poor") { sig.textContent = "POOR"; }
  else { sig.textContent = "OFFLINE"; sig.classList.add("offline"); }
}

function applyStatus(s) {
  if (!s) return;

  $("fpsVal").textContent = (s.fps ?? 0).toFixed(1);

  const lock = $("lockVal");
  const ss = s.search_state || "idle";
  if (ss === "locked")         { lock.textContent = "LOCKED";  lock.className = "stat-value lock acquired"; }
  else if (ss === "searching") { lock.textContent = "SEARCH";  lock.className = "stat-value lock searching"; }
  else if (ss === "acquiring") { lock.textContent = "ACQUIRE"; lock.className = "stat-value lock"; }
  else                         { lock.textContent = "IDLE";    lock.className = "stat-value lock"; }

  if (s.mode && s.mode !== state.mode) setModeUI(s.mode);
  if (s.color) setColorUI(s.color);

  if (s.frame_w && s.frame_h) {
    $("resolutionMeta").textContent = `${s.frame_w}×${s.frame_h}`;
  }

  if (s.rssi != null) $("rssiVal").textContent = s.rssi;
  if (s.pid) $("pidMeta").textContent = `E:${s.pid.error} T:${s.pid.turn} F:${s.pid.fwd}`;

  // Shadow state
  const shadowEl = $("shadowStateMeta");
  if (shadowEl) {
    const ss2 = (s.shadow_state || "idle").toUpperCase();
    shadowEl.textContent = ss2;
    shadowEl.className = "card-meta shadow-" + (s.shadow_state || "idle");
  }

  // Intel panel — shown for both RECON (person) and SHADOW
  const intelCard = $("intelCard");
  if (intelCard) {
    const showIntel = s.mode === "shadow" || s.mode === "person";
    intelCard.hidden = !showIntel;
    if (showIntel) {
      const i = s.intel || {};
      const hasData = !!s.intel;
      $("intelTargetState").textContent = hasData
        ? (i.is_moving ? "MOVING" : "STOPPED")
        : "ACQUIRING";
      $("intelTargetState").className = "intel-value " + (
        hasData ? (i.is_moving ? "intel-moving" : "intel-stopped") : "intel-stopped"
      );
      $("intelSpeed").textContent = hasData ? (i.speed?.toFixed(1) ?? "--") : "--";
      $("intelBehavior").textContent = (i.behavior || "acquiring").toUpperCase();
      $("intelMovingPct").textContent = (i.moving_pct ?? 0) + "%";
      $("intelStops").textContent = i.total_stops ?? "--";
      $("intelDirection").textContent = (i.direction || "unknown").toUpperCase();
      $("intelSummary").textContent = i.summary || "Awaiting target detection...";
    }
  }

  // Obstacle indicator
  const obsEl = $("obstacleVal");
  const obsUnit = $("obstacleUnit");
  if (s.obstacle_dist != null && s.obstacle_dist >= 0) {
    obsEl.textContent = Math.round(s.obstacle_dist);
    obsUnit.textContent = "cm";
    if (s.obstacle_dist <= 15) {
      obsEl.className = "stat-value obstacle-danger";
    } else if (s.obstacle_dist <= 40) {
      obsEl.className = "stat-value obstacle-warn";
    } else {
      obsEl.className = "stat-value obstacle-clear";
    }
  } else if (s.obstacle_cam) {
    obsEl.textContent = "WARN";
    obsUnit.textContent = "CAM";
    obsEl.className = "stat-value obstacle-warn";
  } else {
    obsEl.textContent = "CLEAR";
    obsUnit.textContent = "";
    obsEl.className = "stat-value obstacle-clear";
  }

  // Scene description
  const sceneEl = $("sceneText");
  if (sceneEl && s.scene) {
    sceneEl.textContent = s.scene;
  }

  renderDetections(s.detections || [], s);
  drawOverlay(s);
  maybeNarrate(s);
}

function classify(d, mode, color) {
  if (mode === "person") return "UNKNOWN";
  if (mode === "color")  return COLOR_CLASSIFY[color] || "UNKNOWN";
  return "UNKNOWN";
}

function renderDetections(dets, s) {
  $("detCount").textContent = String(dets.length).padStart(2, "0");
  const list = $("detectionList");
  if (dets.length === 0) {
    list.innerHTML = '<li class="empty">NO CONTACTS</li>';
    return;
  }
  list.innerHTML = dets.map((d, i) => {
    const conf = Math.round((d.confidence ?? 0) * 100);
    const cls = classify(d, s.mode, s.color);
    const score = d.score != null ? ` · ${Math.round(d.score * 100)}` : '';
    return `<li class="${d.is_target ? 'target' : ''}" data-idx="${i}">
      <span class="det-dot"></span>
      <span class="det-label">${escapeHtml(d.label)}</span>
      <span class="det-conf-bar"><i style="width:${conf}%"></i></span>
      <span class="det-conf">${conf}%${score}</span>
      <span class="det-tag" data-class="${cls}">${cls}</span>
    </li>`;
  }).join("");

  // Click detection list item to select target
  list.querySelectorAll('li[data-idx]').forEach((li) => {
    li.style.cursor = 'pointer';
    li.addEventListener('click', () => {
      if (!state.brainUrl) return;
      const idx = parseInt(li.dataset.idx);
      brainFetch(`/select_target`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: idx }),
      }).catch(() => {});
      logEvent('info', 'TARGET', `Selected contact #${idx}`);
      narrate('Target designated');
    });
  });
}

function drawOverlay(s) {
  resizeOverlay();
  const dpr = window.devicePixelRatio || 1;
  const dw = overlay.width / dpr;
  const dh = overlay.height / dpr;
  octx.clearRect(0, 0, dw, dh);

  if (!s || !s.frame_w || !s.frame_h) return;

  const srcW = s.frame_w, srcH = s.frame_h;
  const scale = Math.min(dw / srcW, dh / srcH);
  const drawW = srcW * scale;
  const drawH = srcH * scale;
  const offX = (dw - drawW) / 2;
  const offY = (dh - drawH) / 2;

  const dets = s.detections || [];
  for (const d of dets) {
    const [x1, y1, x2, y2] = d.bbox;
    const rx = offX + x1 * scale;
    const ry = offY + y1 * scale;
    const rw = (x2 - x1) * scale;
    const rh = (y2 - y1) * scale;

    const cls = classify(d, s.mode, s.color);
    const color = classColor(cls);
    const isT = d.is_target;

    octx.strokeStyle = color;
    octx.shadowColor = color;
    octx.shadowBlur = isT ? 14 : 4;
    octx.lineWidth = isT ? 2.5 : 1.5;

    // corner brackets only (tactical look)
    const c = Math.min(18, rw * 0.25, rh * 0.25);
    octx.beginPath();
    octx.moveTo(rx, ry + c); octx.lineTo(rx, ry); octx.lineTo(rx + c, ry);
    octx.moveTo(rx + rw - c, ry); octx.lineTo(rx + rw, ry); octx.lineTo(rx + rw, ry + c);
    octx.moveTo(rx + rw, ry + rh - c); octx.lineTo(rx + rw, ry + rh); octx.lineTo(rx + rw - c, ry + rh);
    octx.moveTo(rx + c, ry + rh); octx.lineTo(rx, ry + rh); octx.lineTo(rx, ry + rh - c);
    octx.stroke();

    if (isT) {
      octx.globalAlpha = 0.35;
      octx.strokeRect(rx, ry, rw, rh);
      octx.globalAlpha = 1;
    }

    octx.shadowBlur = 0;
    const label = `${d.label.toUpperCase()} ${Math.round((d.confidence ?? 0) * 100)}% · ${cls}`;
    octx.font = "600 10px 'JetBrains Mono', monospace";
    const tw = octx.measureText(label).width + 10;
    octx.fillStyle = color;
    octx.fillRect(rx, ry - 18, tw, 16);
    octx.fillStyle = "#000";
    octx.fillText(label, rx + 5, ry - 6);
  }

  if (s.target) {
    const tx = offX + s.target.x * scale;
    const ty = offY + s.target.y * scale;
    const cx = offX + drawW / 2;
    const cy = offY + drawH / 2;
    octx.strokeStyle = "rgba(106, 255, 184, 0.55)";
    octx.lineWidth = 1;
    octx.setLineDash([4, 4]);
    octx.beginPath();
    octx.moveTo(cx, cy);
    octx.lineTo(tx, ty);
    octx.stroke();
    octx.setLineDash([]);

    octx.fillStyle = "rgba(106, 255, 184, 0.95)";
    octx.beginPath();
    octx.arc(tx, ty, 3, 0, Math.PI * 2);
    octx.fill();

    // distance indicator
    const dist = Math.round(Math.hypot(tx - cx, ty - cy) / scale);
    octx.font = "600 10px 'JetBrains Mono', monospace";
    octx.fillStyle = "rgba(106, 255, 184, 0.8)";
    octx.fillText(`OFFSET ${dist}px`, cx + 8, cy - 8);
  }

  // Obstacle warning bar at bottom
  if (s.obstacle_dist != null && s.obstacle_dist >= 0 && s.obstacle_dist <= 40) {
    const danger = Math.max(0, 1 - s.obstacle_dist / 40);
    const barH = 6;
    const barY = dh - barH - 2;
    octx.fillStyle = `rgba(255, ${Math.round(60 + 140 * (1 - danger))}, 59, ${0.4 + danger * 0.5})`;
    octx.fillRect(offX, barY, drawW, barH);
    octx.font = "600 9px 'JetBrains Mono', monospace";
    octx.fillStyle = 'rgba(255, 255, 255, 0.9)';
    octx.fillText(`OBSTACLE ${Math.round(s.obstacle_dist)}cm`, offX + 6, barY - 3);
  } else if (s.obstacle_cam) {
    const barH = 4;
    const barY = dh - barH - 2;
    octx.fillStyle = 'rgba(255, 179, 66, 0.5)';
    octx.fillRect(offX, barY, drawW, barH);
    octx.font = "600 9px 'JetBrains Mono', monospace";
    octx.fillStyle = 'rgba(255, 179, 66, 0.8)';
    octx.fillText('OBSTACLE DETECTED (CAM)', offX + 6, barY - 3);
  }
}

function classColor(cls) {
  return {
    HOSTILE:  "rgba(255, 59, 59, 0.95)",
    FRIENDLY: "rgba(106, 255, 184, 0.95)",
    CAUTION:  "rgba(255, 179, 66, 0.95)",
    UNKNOWN:  "rgba(124, 179, 255, 0.95)",
  }[cls] || "rgba(200, 200, 200, 0.9)";
}

function resizeOverlay() {
  const rect = videoFrame.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  if (overlay.width !== rect.width * dpr || overlay.height !== rect.height * dpr) {
    overlay.width  = rect.width * dpr;
    overlay.height = rect.height * dpr;
    overlay.style.width  = rect.width + "px";
    overlay.style.height = rect.height + "px";
    octx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
}

function maybeNarrate(s) {
  if (!s) return;
  const hasTarget = !!s.target;
  const count = s.detections?.length ?? 0;

  if (state.prevMode !== s.mode) {
    const phrases = {
      manual: "Manual control",
      color:  `Tracking ${s.color} profile. ${COLOR_CLASSIFY[s.color] || "unknown"} classification.`,
      person: "Recon mode active. Personnel tracking online.",
      shadow: "Shadow mode engaged. Stealth tracking active.",
    };
    narrate(phrases[s.mode] || `Mode ${s.mode}`);
    logEvent("info", "MODE", `${s.mode.toUpperCase()}`);
    state.prevMode = s.mode;
  }

  if (hasTarget && !state.prevHasTarget) {
    const t = (s.detections || []).find((d) => d.is_target) || { label: "contact" };
    const cls = classify(t, s.mode, s.color);
    narrate(`${cls.toLowerCase()} contact acquired`);
    logEvent(cls === "HOSTILE" ? "alert" : "warn", "CONTACT", `Lock acquired · ${cls}`);
  } else if (!hasTarget && state.prevHasTarget) {
    narrate("Contact lost");
    logEvent("warn", "CONTACT", "Lock lost");
  } else if (count > state.prevTargetCount && count > 1 && s.mode === "person") {
    narrate(`${count} personnel in view`);
    logEvent("warn", "RECON", `${count} personnel detected`);
  }

  const searchSt = s.search_state || "idle";
  if (searchSt === "searching" && state.prevSearchState !== "searching") {
    narrate("Initiating search sweep");
    logEvent("warn", "SEARCH", "Auto-search engaged");
  }
  state.prevSearchState = searchSt;

  // Shadow state narration
  const shadowSt = s.shadow_state || "idle";
  if (shadowSt !== state.prevShadowState && s.mode === "shadow") {
    const shadowPhrases = {
      follow:  "Shadowing target",
      hold:    "Target stationary. Holding position.",
      conceal: "Moving to cover",
      hidden:  "Concealed. Observing.",
      lost:    "Target lost. Searching.",
    };
    if (shadowPhrases[shadowSt]) {
      narrate(shadowPhrases[shadowSt]);
      logEvent("info", "SHADOW", shadowPhrases[shadowSt]);
    }
  }
  state.prevShadowState = shadowSt;

  // Obstacle narration
  if (s.obstacle_dist != null && s.obstacle_dist <= 15 && s.obstacle_dist >= 0) {
    narrate("Obstacle. Full stop.");
    logEvent("alert", "OBSTACLE", `${Math.round(s.obstacle_dist)}cm — emergency stop`);
  }

  state.prevHasTarget = hasTarget;
  state.prevTargetCount = count;

  // Auto-narrate scene changes
  if (s.scene && s.scene !== state.prevScene && s.scene !== "Nothing detected in view.") {
    narrate(s.scene);
    state.prevScene = s.scene;
  }
}

function narrate(text, opts = {}) {
  if (!text) return;
  if (!state.voiceOn && !opts.force) return;
  if (!("speechSynthesis" in window)) return;

  $("commsText").textContent = text.toUpperCase();

  const now = Date.now();
  if (!opts.force && now - state.lastSpoken < 1500) return;
  if (!opts.force && text === state.lastSpokenText && now - state.lastSpoken < 5000) return;
  state.lastSpoken = now;
  state.lastSpokenText = text;

  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.0;
  u.pitch = 0.9;
  u.volume = 0.95;
  u.onstart = () => { state.speaking = true; $("commsIcon").classList.add("speaking"); };
  u.onend = u.onerror = () => { state.speaking = false; $("commsIcon").classList.remove("speaking"); };
  window.speechSynthesis.speak(u);
}

function logEvent(kind, tag, text) {
  const t = new Date();
  const ts = `${String(t.getHours()).padStart(2,"0")}:${String(t.getMinutes()).padStart(2,"0")}:${String(t.getSeconds()).padStart(2,"0")}`;
  state.log.unshift({ kind, tag, text, ts });
  if (state.log.length > MAX_LOG) state.log.length = MAX_LOG;
  renderLog();
}

function renderLog() {
  const list = $("missionLog");
  $("logCount").textContent = String(state.log.length).padStart(2, "0");
  if (state.log.length === 0) { list.innerHTML = '<li class="empty">LOG EMPTY</li>'; return; }
  list.innerHTML = state.log.map((e) => `
    <li class="${e.kind}">
      <span class="log-time">${e.ts}</span>
      <span class="log-tag">${escapeHtml(e.tag)}</span>
      <span class="log-text">${escapeHtml(e.text)}</span>
    </li>`).join("");
}

async function setMode(mode) {
  setModeUI(mode);
  if (!state.brainUrl) { logEvent("warn", "MODE", `${mode.toUpperCase()} (offline)`); return; }
  try {
    await brainFetch(`/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  } catch (_) {}
}

function setModeUI(mode) {
  state.mode = mode;
  document.querySelectorAll("#modeSwitch button").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  $("colorCard").hidden    = mode !== "color";
  $("joystickCard").hidden = mode !== "manual";
  if ($("intelCard")) $("intelCard").hidden = mode !== "shadow" && mode !== "person";

  const roe = {
    manual: "ROE: MANUAL",
    color:  "ROE: TRACK",
    person: "ROE: FOLLOW",
    shadow: "ROE: SHADOW",
  }[mode] || "ROE: OBSERVE";
  $("roeLabel").textContent = roe;
}

async function setColor(color) {
  setColorUI(color);
  const cls = COLOR_CLASSIFY[color] || "UNKNOWN";
  logEvent("info", "PROFILE", `${color.toUpperCase()} · ${cls}`);
  if (!state.brainUrl) return;
  try {
    await brainFetch(`/color`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset: color }),
    });
  } catch (_) {}
}

function setColorUI(color) {
  state.color = color;
  document.querySelectorAll("#colorRow button").forEach((b) => {
    b.classList.toggle("active", b.dataset.color === color);
  });
}

async function halt() {
  logEvent("alert", "HALT", "Emergency halt triggered");
  narrate("All stop", { force: true });
  if (!state.brainUrl) return;
  try { await brainFetch(`/stop`, { method: "POST" }); } catch (_) {}
}

function connectWS() {
  if (state.ws) { state.ws.close(); state.ws = null; }
  if (!state.brainUrl) return;
  let wsUrl = state.brainUrl.replace(/^http/, "ws") + "/ws";
  if (state.token) wsUrl += `?token=${encodeURIComponent(state.token)}`;
  try {
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => {
      state.ws = ws;
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      logEvent("info", "UPLINK", "Real-time link active");
      narrate("Real-time link active");
    };
    ws.onmessage = (e) => {
      try {
        const s = JSON.parse(e.data);
        state.lastStatus = s;
        state.lastStatusMs = Date.now();
        state.missedPolls = 0;
        if (state.link !== "online") {
          state.link = "online";
          setLinkPill("online");
        }
        if (s.stream_url && !state.streamUrl) {
          startStream(s.stream_url);
          narrate("Camera feed acquired");
        }
        applyStatus(s);
      } catch (_) {}
    };
    ws.onclose = () => {
      state.ws = null;
      if (!state.pollTimer) {
        state.pollTimer = setInterval(pollStatus, 400);
        logEvent("warn", "UPLINK", "Real-time link lost, polling fallback");
      }
    };
    ws.onerror = () => ws.close();
  } catch (_) {}
}

async function fetchTune() {
  if (!state.brainUrl) return;
  try {
    const r = await brainFetch(`/tune`);
    const t = await r.json();
    if ($("kpSlider"))    { $("kpSlider").value = t.kp;            $("kpVal").textContent = t.kp; }
    if ($("kiSlider"))    { $("kiSlider").value = t.ki;            $("kiVal").textContent = t.ki; }
    if ($("kdSlider"))    { $("kdSlider").value = t.kd;            $("kdVal").textContent = t.kd; }
    if ($("speedSlider")) { $("speedSlider").value = t.base_speed; $("speedVal").textContent = t.base_speed; }
    if ($("areaSlider"))  { $("areaSlider").value = t.target_area; $("areaVal").textContent = t.target_area; }
  } catch (_) {}
}

function debounceTune() {
  clearTimeout(state.tuneDebounce);
  state.tuneDebounce = setTimeout(sendTune, 150);
}

async function sendTune() {
  if (!state.brainUrl) return;
  try {
    await brainFetch(`/tune`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kp: parseFloat($("kpSlider").value),
        ki: parseFloat($("kiSlider").value),
        kd: parseFloat($("kdSlider").value),
        base_speed: parseInt($("speedSlider").value),
        target_area: parseInt($("areaSlider").value),
      }),
    });
  } catch (_) {}
}

function driveMetaText() {
  const forward = Math.round(-state.joyY * 200);
  const turn    = Math.round( state.joyX * 180);
  const l = clamp(forward + turn, -255, 255);
  const r = clamp(forward - turn, -255, 255);
  const fmt = (v) => String(Math.abs(v)).padStart(3, "0") + (v < 0 ? "-" : v > 0 ? "+" : " ");
  return `L ${fmt(l)} · R ${fmt(r)}`;
}

async function driveTick() {
  if (state.mode !== "manual") return;
  if (!state.brainUrl) return;
  if (state.driveInFlight) return;
  const forward = Math.round(-state.joyY * 200);
  const turn    = Math.round( state.joyX * 180);
  const l = clamp(forward + turn, -255, 255);
  const r = clamp(forward - turn, -255, 255);
  if (state.driveAbort) state.driveAbort.abort();
  state.driveAbort = new AbortController();
  state.driveInFlight = true;
  try {
    await brainFetch(`/drive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ l, r }),
      signal: state.driveAbort.signal,
    });
  } catch (_) {} finally {
    state.driveInFlight = false;
  }
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function setupJoystick(el, stick, onMove) {
  let active = false;
  let pointerId = null;
  const rect = () => el.getBoundingClientRect();

  const move = (clientX, clientY) => {
    const r = rect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const maxR = r.width / 2 - 18;
    let dx = clientX - cx;
    let dy = clientY - cy;
    const d = Math.hypot(dx, dy);
    if (d > maxR) { dx = (dx / d) * maxR; dy = (dy / d) * maxR; }
    stick.style.transform = `translate(${dx}px, ${dy}px)`;
    onMove(dx / maxR, dy / maxR);
  };

  const release = () => {
    active = false; pointerId = null;
    stick.style.transform = "translate(0,0)";
    onMove(0, 0);
  };

  el.addEventListener("pointerdown", (e) => {
    active = true; pointerId = e.pointerId;
    el.setPointerCapture(e.pointerId);
    move(e.clientX, e.clientY);
  });
  el.addEventListener("pointermove", (e) => {
    if (!active || e.pointerId !== pointerId) return;
    move(e.clientX, e.clientY);
  });
  el.addEventListener("pointerup",     release);
  el.addEventListener("pointercancel", release);
  el.addEventListener("pointerleave",  () => { if (active) release(); });
}

// ── Servo control ──

function debounceServo() {
  clearTimeout(state.servoDebounce);
  state.servoDebounce = setTimeout(sendServo, 100);
}

async function sendServo() {
  if (!state.brainUrl) return;
  if (state.servoInFlight) return;
  state.servoInFlight = true;
  try {
    await brainFetch(`/servo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pan:  parseInt($("panSlider").value),
        tilt: parseInt($("tiltSlider").value),
      }),
    });
  } catch (_) {} finally {
    state.servoInFlight = false;
  }
}

async function centerServo() {
  if (!state.brainUrl) return;
  try {
    await brainFetch(`/servo/center`, { method: "POST" });
    $("panSlider").value = 90;  $("panVal").textContent = "90";
    $("tiltSlider").value = 90; $("tiltVal").textContent = "90";
    $("servoMeta").textContent = "PAN 90 \u00b7 TILT 90";
    logEvent("info", "SERVO", "Servos centred");
  } catch (_) {}
}
