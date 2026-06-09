"""
================================================================================
        ARES — Calculadora segura (sin `eval`)
================================================================================
Convierte una frase en español a una expresión aritmética y la evalúa con
un visitor de AST que SOLO permite:
  • Constantes numéricas
  • Operadores +, -, *, /, %, **, // y -unario
  • Llamadas a una whitelist de funciones de `math` (sqrt, log, sin, ...)
  • Constantes `pi` y `e`

NUNCA usa `eval`/`exec` directamente.

Función pública:
  evaluar(expr_o_frase: str) -> Dict[str, Any]
================================================================================
"""

from __future__ import annotations

import ast
import math
import operator as op
import re
from typing import Any, Dict, Optional

from icecream import ic


# ============================== WHITELISTS ==============================
_OPS_BIN = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.FloorDiv: op.floordiv,
}
_OPS_UN = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}
_FUNCS = {
    "sqrt":  math.sqrt,
    "raiz":  math.sqrt,
    "abs":   abs,
    "log":   math.log,
    "log10": math.log10,
    "log2":  math.log2,
    "exp":   math.exp,
    "sin":   math.sin,
    "cos":   math.cos,
    "tan":   math.tan,
    "asin":  math.asin,
    "acos":  math.acos,
    "atan":  math.atan,
    "ceil":  math.ceil,
    "floor": math.floor,
    "round": round,
    "factorial": math.factorial,
    "max":   max,
    "min":   min,
    "pow":   pow,
}
_CONSTS = {
    "pi": math.pi,
    "e":  math.e,
    "tau": math.tau,
}


class _ExpresionInsegura(ValueError):
    pass


# ============================== EVALUADOR ==============================
def _eval_ast(node):
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise _ExpresionInsegura(f"Constante no numérica: {node.value!r}")
    if isinstance(node, ast.Num):  # Python <3.8 fallback
        return node.n
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _OPS_BIN:
            raise _ExpresionInsegura(f"Operador no permitido: {type(node.op).__name__}")
        return _OPS_BIN[type(node.op)](_eval_ast(node.left), _eval_ast(node.right))
    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _OPS_UN:
            raise _ExpresionInsegura(f"Operador unario no permitido: {type(node.op).__name__}")
        return _OPS_UN[type(node.op)](_eval_ast(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise _ExpresionInsegura("Solo se permiten funciones por nombre")
        if node.func.id not in _FUNCS:
            raise _ExpresionInsegura(f"Función no permitida: {node.func.id}")
        args = [_eval_ast(a) for a in node.args]
        return _FUNCS[node.func.id](*args)
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise _ExpresionInsegura(f"Identificador no permitido: {node.id}")
    raise _ExpresionInsegura(f"Nodo AST no permitido: {type(node).__name__}")


# ============================== TRADUCCIÓN ES → EXPR ==============================
# Reemplazos directos (orden importa: los más largos y específicos primero).
_REEMPLAZOS = [
    # 0) Porcentajes — antes que cualquier "por"
    (r"(\d+(?:\.\d+)?)\s*%\s*de\s*", r"(\1/100)*"),
    (r"(\d+(?:\.\d+)?)\s*por\s+ciento\s+de\s*", r"(\1/100)*"),
    (r"(\d+(?:\.\d+)?)\s*porciento\s+de\s*", r"(\1/100)*"),
    # 1) Funciones que toman argumento — meten paréntesis si falta
    (r"\bra[íi]z\s+cuadrada\s+de\s+(\d+(?:\.\d+)?)", r"sqrt(\1)"),
    (r"\bra[íi]z\s+de\s+(\d+(?:\.\d+)?)", r"sqrt(\1)"),
    (r"\blogaritmo\s+(?:de\s+)?(\d+(?:\.\d+)?)", r"log(\1)"),
    (r"\bseno\s+de\s+(\d+(?:\.\d+)?)", r"sin(\1)"),
    (r"\bcoseno\s+de\s+(\d+(?:\.\d+)?)", r"cos(\1)"),
    (r"\btangente\s+de\s+(\d+(?:\.\d+)?)", r"tan(\1)"),
    (r"\bfactorial\s+de\s+(\d+)", r"factorial(\1)"),
    (r"\b(?:el\s+)?valor\s+absoluto\s+de\s+(-?\d+(?:\.\d+)?)", r"abs(\1)"),
    # 2) Potencias (frase) — ANTES que el reemplazo simple de "por"
    (r"\belev[ao]d[oa]\s+a\s+la\s+(?:potencia\s+de\s+)?", "**"),
    (r"\belev[ao]d[oa]\s+a\s+", "**"),
    (r"\bal\s+cuadrado\b", "**2"),
    (r"\bal\s+cubo\b", "**3"),
    # 3) Operadores básicos — orden: divisiones específicas antes que "por"
    (r"\bdividido\s+(?:por|entre)\b", "/"),
    (r"\bm[áa]s\b", "+"),
    (r"\bmenos\b", "-"),
    (r"\bmultiplicado\s+por\b", "*"),
    (r"\bpor\b", "*"),                         # tras divisiones y "por ciento"
    (r"\bentre\b", "/"),
    (r"\bdiv\b", "/"),
    (r"\bmult\b", "*"),
    (r"\bm[óo]dulo\b", "%"),
    (r"\b(?:residuo|resto)\b", "%"),
    # 4) Constantes
    (r"\bpi\b", "pi"),
]

# Prefijos a ignorar al inicio (cuánto es / calcula / etc).
_PREFIJO = re.compile(
    r"^\s*(?:cu[áa]nto\s+es|cu[áa]nto\s+da|calcula(?:me)?|c[áa]lculo\s+de|"
    r"resuelve|resu[ée]lveme|cu[áa]l\s+es\s+el\s+resultado\s+de|"
    r"dime\s+cu[áa]nto\s+es|dime\s+el\s+resultado\s+de|"
    r"el\s+resultado\s+de|"
    r"qu[eé]\s+(?:es|da|resulta)\s+(?:de\s+)?)\s*",
    re.IGNORECASE,
)


def _frase_a_expresion(texto: str) -> str:
    """Convierte una frase en español a una expresión aritmética."""
    t = texto.strip().rstrip("?.!¿¡").strip()
    t = _PREFIJO.sub("", t)
    # Coma decimal española → punto
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    for pat, rep in _REEMPLAZOS:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    # Espacios alrededor de operadores
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ============================== API PÚBLICA ==============================
def parece_calculo(texto: str) -> bool:
    """¿La frase parece una operación matemática? Útil para detección de
    intención sin colisionar con preguntas conceptuales."""
    if not texto:
        return False
    t = texto.lower()
    # 1) Frases típicas
    palabras_clave = (
        "cuánto es", "cuanto es", "calcula", "cálculo", "calculo",
        "resuelve", "resultado de", "raíz cuadrada", "raiz cuadrada",
        "factorial", "logaritmo", "porciento", "por ciento",
        "elevado", "al cuadrado", "al cubo",
    )
    if any(k in t for k in palabras_clave):
        return True
    # 2) Expresión que ya parece aritmética: contiene un operador y
    # al menos un dígito.
    if re.search(r"\d", t) and re.search(r"[+\-*/%^]|\*\*", t):
        return True
    # 3) "X más Y", "X por Y", "X entre Y"
    if re.search(r"\d.*\b(m[áa]s|menos|por|entre|dividido|multiplicado)\b.*\d", t):
        return True
    return False


def evaluar(expr_o_frase: str) -> Dict[str, Any]:
    """
    Evalúa una expresión matemática (o una frase en español) de forma segura.
    Devuelve {ok, resultado, expresion} o {ok=False, error}.
    """
    if not expr_o_frase or not expr_o_frase.strip():
        return {"ok": False, "error": "Expresión vacía"}

    expr = _frase_a_expresion(expr_o_frase)
    if not expr:
        return {"ok": False, "error": "No reconocí la operación"}

    try:
        tree = ast.parse(expr, mode="eval")
        valor = _eval_ast(tree)
    except _ExpresionInsegura as e:
        return {"ok": False, "error": f"No permitido: {e}", "expresion": expr}
    except ZeroDivisionError:
        return {"ok": False, "error": "División entre cero", "expresion": expr}
    except (SyntaxError, ValueError, TypeError) as e:
        return {"ok": False, "error": f"No pude evaluar: {e}", "expresion": expr}

    # Formatear: enteros sin decimales, floats redondeados a 6
    if isinstance(valor, float):
        if math.isnan(valor) or math.isinf(valor):
            return {"ok": False, "error": "Resultado no finito", "expresion": expr}
        if valor.is_integer():
            valor_fmt: Any = int(valor)
        else:
            valor_fmt = round(valor, 6)
    else:
        valor_fmt = valor

    ic(f" {expr} = {valor_fmt}")
    return {"ok": True, "resultado": valor_fmt, "expresion": expr}
