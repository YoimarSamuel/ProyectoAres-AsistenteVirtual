/* ARES — Login & Register controller */

const tabs        = document.querySelectorAll(".tab");
const formLogin   = document.getElementById("formLogin");
const formReg     = document.getElementById("formRegister");
const policyText  = document.getElementById("policyText");
const loginMsg    = document.getElementById("loginMsg");
const regMsg      = document.getElementById("regMsg");

// ----------- TABS -----------
tabs.forEach(tab => {
    tab.addEventListener("click", () => {
        tabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        const target = tab.dataset.tab;
        formLogin.classList.toggle("active", target === "login");
        formReg.classList.toggle("active",   target === "register");
    });
});

// ----------- POLICY -----------
fetch("/api/auth/politica")
    .then(r => r.json())
    .then(d => { policyText.textContent = d.politica || "Política no disponible."; })
    .catch(() => { policyText.textContent = "Política no disponible."; });

// ----------- LOGIN -----------
formLogin.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginMsg.textContent = "Verificando…";
    loginMsg.className = "auth-msg";
    try {
        const r = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({
                username: document.getElementById("loginUser").value.trim(),
                password: document.getElementById("loginPass").value
            })
        });
        const d = await r.json();
        if (d.ok) {
            loginMsg.textContent = "Bienvenido. Redirigiendo…";
            loginMsg.className = "auth-msg ok";
            setTimeout(() => window.location.href = "/", 600);
        } else {
            loginMsg.textContent = d.mensaje || "Error";
            loginMsg.className = "auth-msg error";
        }
    } catch (err) {
        loginMsg.textContent = "Error de conexión";
        loginMsg.className = "auth-msg error";
    }
});

// ----------- REGISTER -----------
formReg.addEventListener("submit", async (e) => {
    e.preventDefault();
    regMsg.textContent = "Creando cuenta…";
    regMsg.className = "auth-msg";

    const acepta = document.getElementById("acceptPolicy").checked;
    if (!acepta) {
        regMsg.textContent = "Debes aceptar la política para continuar.";
        regMsg.className = "auth-msg error";
        return;
    }

    try {
        const r = await fetch("/api/auth/registrar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                nombre_real:     document.getElementById("regName").value.trim(),
                username:        document.getElementById("regUser").value.trim(),
                password:        document.getElementById("regPass").value,
                tono:            document.getElementById("regTono").value,
                acepta_politica: true
            })
        });
        const d = await r.json();
        if (d.ok) {
            regMsg.textContent = "Cuenta creada. Iniciando sesión…";
            regMsg.className = "auth-msg ok";
            // auto-login
            const lr = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify({
                    username: document.getElementById("regUser").value.trim(),
                    password: document.getElementById("regPass").value
                })
            });
            const ld = await lr.json();
            if (ld.ok) {
                setTimeout(() => window.location.href = "/", 700);
            }
        } else {
            regMsg.textContent = d.mensaje || "Error en registro";
            regMsg.className = "auth-msg error";
        }
    } catch (err) {
        regMsg.textContent = "Error de conexión";
        regMsg.className = "auth-msg error";
    }
});
