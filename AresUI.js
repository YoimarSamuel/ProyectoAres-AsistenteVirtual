/* =====================================================================
   ARES v3.0 — Dashboard Controller
===================================================================== */

const $ = (sel) => document.querySelector(sel);
const els = {
    // Topbar
    clockTime:  $("#clockTime"),
    clockDate:  $("#clockDate"),
    userPill:   $("#userPill"),
    btnLogout:  $("#btnLogout"),
    btnDonar:   $("#btnDonar"),
    topWeather: $("#topWeather"),

    // System Stats
    cpuPct:    $("#cpuPct"),
    cpuBar:    $("#cpuBar"),
    ramPct:    $("#ramPct"),
    ramBar:    $("#ramBar"),
    statsCpu:  $("#statsCpu"),
    statsMem:  $("#statsMem"),
    statsDisk: $("#statsDisk"),

    // Weather
    weatherTemp:  $("#weatherTemp"),
    weatherLoc:   $("#weatherLoc"),
    weatherDesc:  $("#weatherDesc"),
    weatherIcon:  $("#weatherIcon"),
    weatherHum:   $("#weatherHum"),
    weatherWind:  $("#weatherWind"),
    weatherFeels: $("#weatherFeels"),

    // Camera
    camStream:    $("#camStream"),
    camOverlay:   $("#camOverlay"),
    camTags:      $("#camTags"),
    btnCamToggle: $("#btnCamToggle"),

    // Uptime
    uptimeBig:   $("#uptimeBig"),
    uptimeMini:  $("#uptimeMini"),
    upSession:   $("#upSession"),
    upCommands:  $("#upCommands"),
    loadPct:     $("#loadPct"),
    loadBar:     $("#loadBar"),

    // Core
    coreCenter:     $("#coreCenter"),
    coreStatusText: $("#coreStatusText"),

    // Toolbar
    btnMic:      $("#btnMic"),
    btnCapture:  $("#btnCapture"),
    btnKeyboard: $("#btnKeyboard"),

    // Conversation
    convoStream: $("#convoStream"),
    convoForm:   $("#convoForm"),
    convoInput:  $("#convoInput"),
    convoSend:   $("#convoSend"),
    btnClear:    $("#btnClear"),
    btnExport:   $("#btnExport"),
    firstTime:   $("#firstTime"),

    // Donate modal
    donateModal: $("#donateModal"),
    modalClose:  $("#modalClose"),
    donAmount:   $("#donAmount"),
    donCurrency: $("#donCurrency"),
    donGo:       $("#donGo"),
    donNote:     $("#donNote"),
    amtChips:    document.querySelectorAll(".amt-chip"),

    // Refresh buttons
    refreshBtns: document.querySelectorAll(".w-refresh[data-refresh]")
};

// =========== STATE ===========
let micActive = true;       // Por defecto: mic encendido
let camActive = true;
let _voiceSSE = null;       // EventSource para transcripciones en vivo

// =========== HELPERS ===========
const fetchJSON = async (url, opts = {}) => {
    const r = await fetch(url, { credentials: "include", ...opts });
    if (r.status === 401) { window.location.href = "/login"; throw new Error("auth"); }
    return r.json();
};

const fmtTime = (d = new Date()) =>
    d.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true });

const fmtDate = (d = new Date()) =>
    d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });

const nowHHMM = () =>
    new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });

const setCoreState = (state) => {
    els.coreCenter.classList.remove("listening", "processing", "responding");
    if (state === "listening")  els.coreCenter.classList.add("listening");
    if (state === "processing") els.coreCenter.classList.add("processing");
    if (state === "responding") els.coreCenter.classList.add("responding");

    const txt = {
        idle:       "Sistema en línea",
        listening:  "Escuchando…",
        processing: "Procesando…",
        responding: "Respondiendo"
    };
    els.coreStatusText.textContent = txt[state] || "Sistema en línea";
};

// =========== CLOCK ===========
function tickClock() {
    const d = new Date();
    els.clockTime.textContent = fmtTime(d);
    els.clockDate.textContent = fmtDate(d);
}
setInterval(tickClock, 1000);
tickClock();

// =========== TEXT-TO-SPEECH (navegador) ===========
let ttsEnabled = true;
let _voiceES = null;

function _pickSpanishVoice() {
    const voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
    if (!voices.length) return null;
    // Preferir voz masculina latina; si no, cualquier español; si no, la 1ª
    const pref = ["es-mx", "es-us", "es-419", "es-co", "es-es", "es"];
    for (const p of pref) {
        const v = voices.find(v => (v.lang || "").toLowerCase().startsWith(p));
        if (v) return v;
    }
    return voices.find(v => (v.lang || "").toLowerCase().startsWith("es")) || null;
}

function speak(text) {
    if (!ttsEnabled || !text) return;
    if (!("speechSynthesis" in window)) return;
    // Limpiar emojis/símbolos para una lectura natural
    const limpio = text.replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}]/gu, "").trim();
    if (!limpio) return;
    try {
        speechSynthesis.cancel();              // corta lo anterior
        const u = new SpeechSynthesisUtterance(limpio);
        u.lang = "es-ES";
        u.rate = 1.0;
        u.pitch = 1.0;
        if (!_voiceES) _voiceES = _pickSpanishVoice();
        if (_voiceES) u.voice = _voiceES;
        speechSynthesis.speak(u);
    } catch (e) { /* ignore */ }
}

// Las voces se cargan de forma asíncrona en algunos navegadores
if ("speechSynthesis" in window) {
    speechSynthesis.onvoiceschanged = () => { _voiceES = _pickSpanishVoice(); };
}

// =========== CHAT ===========
function addMsg(text, type = "ares", thinking = false) {
    const m = document.createElement("div");
    m.className = `msg msg-${type}` + (thinking ? " thinking" : "");
    m.innerHTML = `<p></p><span class="msg-time">${nowHHMM()}</span>`;
    m.querySelector("p").textContent = text;
    els.convoStream.appendChild(m);
    els.convoStream.scrollTop = els.convoStream.scrollHeight;
    // Leer en voz alta TODO lo que dice ARES (no el "pensando", no lo del usuario)
    if (type === "ares" && !thinking) speak(text);
    return m;
}

async function enviarMensaje(texto, hablar = false) {
    if (!texto) return;
    addMsg(texto, "user");
    els.convoInput.value = "";
    els.convoInput.disabled = true;
    els.convoSend.disabled = true;

    setCoreState("processing");
    const thinking = addMsg("…", "ares", true);

    try {
        const r = await fetchJSON("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mensaje: texto, hablar })
        });
        thinking.remove();

        if (r.respuesta) {
            setCoreState("responding");
            addMsg(r.respuesta, "ares");
            const ms = Math.min(7000, 1500 + r.respuesta.length * 38);
            setTimeout(() => setCoreState(micActive ? "listening" : "idle"), ms);
        } else {
            setCoreState(micActive ? "listening" : "idle");
        }
    } catch (err) {
        thinking.remove();
        setCoreState("idle");
        addMsg(" Error de conexión", "ares");
    } finally {
        els.convoInput.disabled = false;
        els.convoSend.disabled = false;
        els.convoInput.focus();
    }
}

els.convoForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = els.convoInput.value.trim();
    if (v) enviarMensaje(v, false);
});

els.btnClear.addEventListener("click", () => {
    els.convoStream.innerHTML = "";
    addMsg("Conversación limpiada. ¿En qué puedo asistirte?", "ares");
});

els.btnExport.addEventListener("click", () => {
    const msgs = [...document.querySelectorAll(".msg")].map(m => {
        const role = m.classList.contains("msg-user") ? "TÚ" : "ARES";
        return `[${role}] ${m.querySelector("p").textContent}`;
    }).join("\n");
    const blob = new Blob([msgs], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ares-chat-${Date.now()}.txt`;
    a.click();
});

// Toolbar
els.btnKeyboard.addEventListener("click", () => els.convoInput.focus());

els.btnCapture.addEventListener("click", async () => {
    const img = els.camStream;
    if (!img.naturalWidth) return;
    const c = document.createElement("canvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    c.getContext("2d").drawImage(img, 0, 0);
    const a = document.createElement("a");
    a.href = c.toDataURL("image/png");
    a.download = `ares-capture-${Date.now()}.png`;
    a.click();
});

// Mic toggle
els.btnMic.addEventListener("click", async () => {
    micActive = !micActive;
    els.btnMic.classList.toggle("active", micActive);
    setCoreState(micActive ? "listening" : "idle");
    try {
        if (micActive) {
            await fetchJSON("/api/voz/escucha/iniciar", { method: "POST" });
            startVoiceSSE();
            addMsg(" Escucha por voz activada. Di 'oye ARES' o 'oye Jarvis' seguido de tu petición.", "ares");
        } else {
            await fetchJSON("/api/voz/escucha/detener", { method: "POST" });
            stopVoiceSSE();
            addMsg(" Escucha desactivada.", "ares");
        }
    } catch (e) { /* ignore */ }
});

// =========== VOZ EN VIVO (SSE) ===========
// Cuando el backend transcribe lo que se dice por el mic, lo recibimos aquí
// y lo pintamos en el chat exactamente como si el usuario lo hubiera escrito.
function startVoiceSSE() {
    if (_voiceSSE) return;
    try {
        _voiceSSE = new EventSource("/api/voz/eventos", { withCredentials: true });
        _voiceSSE.onmessage = (ev) => {
            let data;
            try { data = JSON.parse(ev.data); } catch { return; }
            if (data.tipo === "transcripcion") {
                if (!data.texto) return;
                // Pintamos lo dicho como mensaje del usuario.
                addMsg(data.texto + (data.con_wake ? "" : "  ·  (sin 'oye ares')"),
                       "user");
                if (data.con_wake) setCoreState("processing");
            } else if (data.tipo === "respuesta") {
                if (data.texto) {
                    setCoreState("responding");
                    // Pintamos el texto Y lo leemos en voz alta con la
                    // Web Speech API del navegador. El backend ya NO hace
                    // TTS para entradas por voz (pyttsx3 puede salir por
                    // un dispositivo de audio distinto en Windows; el
                    // navegador es más fiable).
                    const m = document.createElement("div");
                    m.className = "msg msg-ares";
                    m.innerHTML = `<p></p><span class="msg-time">${nowHHMM()}</span>`;
                    m.querySelector("p").textContent = data.texto;
                    els.convoStream.appendChild(m);
                    els.convoStream.scrollTop = els.convoStream.scrollHeight;
                    speak(data.texto);
                    setTimeout(() => setCoreState(micActive ? "listening" : "idle"), 1500);
                }
            }
        };
        _voiceSSE.onerror = () => {
            // Reintento implícito de EventSource
        };
    } catch (e) { /* ignore */ }
}

function stopVoiceSSE() {
    if (_voiceSSE) {
        try { _voiceSSE.close(); } catch (e) {}
        _voiceSSE = null;
    }
}

async function autoEncenderMic() {
    // Pide al backend iniciar el mic y abre el canal SSE para mostrar lo
    // transcrito en vivo. Si pyaudio no está disponible, queda en off.
    try {
        const r = await fetchJSON("/api/voz/escucha/iniciar", { method: "POST" });
        if (r && r.ok) {
            micActive = true;
            els.btnMic.classList.add("active");
            setCoreState("listening");
            startVoiceSSE();
        } else {
            micActive = false;
            els.btnMic.classList.remove("active");
            setCoreState("idle");
        }
    } catch (e) {
        micActive = false;
        els.btnMic.classList.remove("active");
        setCoreState("idle");
    }
}

// =========== POLLING ===========
async function pollSistema() {
    try {
        const s = await fetchJSON("/api/sistema");
        if (s.cpu) {
            els.cpuPct.textContent  = `${s.cpu.percent.toFixed(0)}%`;
            els.cpuBar.style.width  = `${Math.min(100, s.cpu.percent)}%`;
            els.statsCpu.textContent = `${s.cpu.percent.toFixed(0)}%`;
        }
        if (s.ram) {
            els.ramPct.textContent  = `${s.ram.percent.toFixed(0)}%`;
            els.ramBar.style.width  = `${Math.min(100, s.ram.percent)}%`;
            els.statsMem.textContent = `${s.ram.usado_gb}/${s.ram.total_gb} GB`;
        }
        if (s.disco) {
            els.statsDisk.textContent = `${s.disco.usado_gb}/${s.disco.total_gb} GB`;
        }
        if (typeof s.load_general === "number") {
            els.loadPct.textContent = `${s.load_general.toFixed(0)}%`;
            els.loadBar.style.width = `${Math.min(100, s.load_general)}%`;
        }
    } catch (e) { /* ignore */ }
}

async function pollUptime() {
    try {
        const u = await fetchJSON("/api/uptime");
        els.uptimeBig.textContent  = u.formateado || "00:00:00";
        els.uptimeMini.textContent = u.formateado || "00:00:00";
        els.upCommands.textContent = u.comandos_ejecutados ?? 0;
    } catch (e) { /* ignore */ }
}

async function pollWeather() {
    try {
        const w = await fetchJSON("/api/clima");
        if (w.error) return;
        els.weatherTemp.textContent  = w.temperatura != null ? `${w.temperatura}°C` : "—°C";
        els.weatherLoc.textContent   = `${w.ciudad}, ${w.pais || ""}`.replace(/, $/, "");
        els.weatherDesc.textContent  = (w.descripcion || "").toLowerCase();
        els.weatherHum.textContent   = w.humedad != null ? `${w.humedad}%` : "—%";
        els.weatherWind.textContent  = w.viento  != null ? `${w.viento.toFixed(1)} m/s` : "— m/s";
        els.weatherFeels.textContent = w.sensacion != null ? `${w.sensacion}°C` : "—°C";
        els.weatherIcon.textContent  = weatherEmoji(w.codigo);

        // Top pill
        els.topWeather.innerHTML = `<span>${w.temperatura ?? "—"}°C</span><span class="city">${w.ciudad ?? ""}</span>`;
    } catch (e) { /* ignore */ }
}

function weatherEmoji(code) {
    if (code == null) return "";
    if (code === 0) return "";
    if (code < 3) return "";
    if (code === 3) return "";
    if (code >= 45 && code <= 48) return "";
    if (code >= 51 && code <= 67) return "";
    if (code >= 71 && code <= 77) return "";
    if (code >= 80 && code <= 82) return "";
    if (code >= 95) return "";
    return "";
}

async function pollCamera() {
    try {
        const c = await fetchJSON("/api/camara/estado");
        const tags = c.objetos_actuales || [];
        els.camTags.innerHTML = tags.slice(0, 6).map(o =>
            `<span class="cam-tag">${o.nombre}</span>`
        ).join("");

        if (c.activa) {
            // Ensure stream is loaded
            if (!els.camStream.src) {
                els.camStream.src = "/api/camara/stream";
                els.camStream.style.display = "block";
            }
            els.camOverlay.classList.remove("show");
        } else {
            els.camOverlay.classList.add("show");
        }
    } catch (e) { /* ignore */ }
}

async function pollProfile() {
    try {
        const p = await fetchJSON("/api/auth/perfil");
        if (p && p.nombre_real) {
            els.userPill.querySelector(".user-name").textContent = p.nombre_real;
        }
    } catch (e) { /* ignore */ }
}

// =========== CAMERA TOGGLE ===========
els.btnCamToggle.addEventListener("click", async () => {
    camActive = !camActive;
    if (camActive) {
        await fetchJSON("/api/camara/iniciar", { method: "POST" });
        els.camStream.src = "/api/camara/stream?ts=" + Date.now();
        els.camStream.style.display = "block";
    } else {
        await fetchJSON("/api/camara/detener", { method: "POST" });
        els.camStream.src = "";
        els.camStream.style.display = "none";
        els.camOverlay.classList.add("show");
    }
});

// =========== LOGOUT ===========
els.btnLogout.addEventListener("click", async () => {
    await fetchJSON("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
});

// =========== MANUAL REFRESHES ===========
els.refreshBtns.forEach(b => {
    b.addEventListener("click", () => {
        const t = b.dataset.refresh;
        if (t === "sistema") pollSistema();
        if (t === "clima")   pollWeather();
    });
});

// =========== DONATIONS ===========
els.btnDonar.addEventListener("click", () => {
    els.donateModal.classList.add("show");
});
els.modalClose.addEventListener("click", () => {
    els.donateModal.classList.remove("show");
});
els.donateModal.addEventListener("click", (e) => {
    if (e.target === els.donateModal) els.donateModal.classList.remove("show");
});

els.amtChips.forEach(c => {
    c.addEventListener("click", () => {
        els.amtChips.forEach(x => x.classList.remove("active"));
        c.classList.add("active");
        els.donAmount.value = c.dataset.amt;
    });
});

els.donGo.addEventListener("click", async () => {
    els.donNote.textContent = "Procesando…";
    els.donNote.className = "donate-note";

    const monto = parseFloat(els.donAmount.value);
    const divisa = els.donCurrency.value;

    if (!monto || monto <= 0) {
        els.donNote.textContent = "Ingresa un monto válido.";
        els.donNote.className = "donate-note error";
        return;
    }

    try {
        const r = await fetchJSON("/api/donaciones/crear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ monto, divisa, pasarela: "auto" })
        });
        if (r.ok && r.url) {
            els.donNote.textContent = "Redirigiendo a la pasarela de pago…";
            window.open(r.url, "_blank", "noopener");
        } else {
            els.donNote.textContent = r.error || "Pasarela no configurada. Configura STRIPE_API_KEY o PAYPAL_ME_HANDLE en .env";
            els.donNote.className = "donate-note error";
        }
    } catch (e) {
        els.donNote.textContent = "Error de red.";
        els.donNote.className = "donate-note error";
    }
});

// =========== BOOT ===========
(function init() {
    setCoreState("idle");
    els.firstTime.textContent = nowHHMM();

    // Leer el saludo inicial que viene fijo en el HTML
    const saludo = els.convoStream.querySelector(".msg-ares p");
    if (saludo) {
        // Algunos navegadores requieren interacción previa; reintenta al 1er clic/tecla
        const intentarSaludo = () => speak(saludo.textContent);
        intentarSaludo();
        const unlock = () => { intentarSaludo();
            window.removeEventListener("click", unlock);
            window.removeEventListener("keydown", unlock); };
        window.addEventListener("click", unlock, { once: true });
        window.addEventListener("keydown", unlock, { once: true });
    }

    // Initial polls
    pollProfile();
    pollSistema();
    pollUptime();
    pollWeather();
    pollCamera();

    // Start MJPEG stream lazily
    setTimeout(() => {
        els.camStream.src = "/api/camara/stream";
    }, 800);

    // Intervals
    setInterval(pollSistema, 2500);
    setInterval(pollUptime,  1000);
    setInterval(pollWeather, 60_000);
    setInterval(pollCamera,  3000);
    setInterval(pollProfile, 30_000);

    setTimeout(() => els.convoInput.focus(), 400);

    // Mic encendido por defecto: arranca el reconocedor del backend y
    // abre el canal SSE para mostrar lo dicho en el chat en vivo.
    setTimeout(autoEncenderMic, 600);
})();
