"""Exporta el mejor modelo del notebook 02 a presentacion/tasador/modelo.json para el tasador en vivo.

Correr desde notebooks/ después del 02:  python3 exportar_tasador.py
Reajusta el pipeline sobre el mismo train (split agrupado, semilla 42) y verifica que la fórmula
exportada reproduzca las predicciones de sklearn.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

from preparar import Preparar, COLS, CAT_TITULO, CATS

DATA = Path("../data")
SALIDA = Path("../presentacion/tasador/modelo.json")

df = pd.read_csv(DATA / "autos_clean.csv")
df[CAT_TITULO] = df[CAT_TITULO].astype("string").fillna("sin_dato")
M = json.loads((DATA / "mejor_modelo.json").read_text(encoding="utf-8"))
assert M["modelo"] == "Ridge"
UMBRAL_INT = M.get("umbral_interaccion")  # solo existe si el mejor modelo usa antigüedad × marca
assert not M["interaccion"] or UMBRAL_INT is not None, "pendiente propia para todas las marcas: no soportado"

idx_tr, idx_te = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
                      .split(df, groups=df["grupo_gemelo"]))
tr, te = df.iloc[idx_tr], df.iloc[idx_te]
pipe = Pipeline([("prep", Preparar(umbral=M["umbral"], interaccion=M["interaccion"],
                                   umbral_interaccion=UMBRAL_INT)),
                 ("reg", Ridge(alpha=M["alpha"]))]).fit(tr[COLS], tr["log_precio"])
prep, reg = pipe.named_steps["prep"], pipe.named_steps["reg"]
coef = reg.coef_

# Numéricas estandarizadas: antigüedad, log(km) y, si hay interacción, una columna
# "antiguedad×<marca>" por marca grande (vale la antigüedad si el auto es de esa marca, 0 si no).
n_num = len(prep.esc_.scale_)
terminos = [{"nombre": n, "media": float(m), "escala": float(e), "coef": float(c)}
            for n, m, e, c in zip(prep.nombres()[:n_num], prep.esc_.mean_, prep.esc_.scale_, coef[:n_num])]
num = {t["nombre"]: t for t in terminos[:2]}
pend_marca = {t["nombre"].split("×", 1)[1]: t for t in terminos[2:]}
cats, inicio = {}, n_num
for col, valores in zip(CATS, prep.ohe_.categories_):
    cats[col] = {str(v): round(float(coef[inicio + j]), 6) for j, v in enumerate(valores)}
    inicio += len(valores)


def predecir(r):
    s = reg.intercept_
    for n in ("antiguedad", "log_km"):
        s += num[n]["coef"] * (r[n] - num[n]["media"]) / num[n]["escala"]
    for marca, t in pend_marca.items():
        x = r["antiguedad"] if r["marca"] == marca else 0.0
        s += t["coef"] * (x - t["media"]) / t["escala"]
    marca_ag = r["marca"] if r["marca"] in prep.marcas_ else "otra_marca"
    clave = r["marca"] + "|" + r["modelo"]
    modelo_ag = clave if clave in prep.modelos_ else marca_ag + "|otro"
    vals = {"marca_ag": marca_ag, "modelo_ag": modelo_ag, "tipo_vendedor": r["tipo_vendedor"],
            **{c: str(r[c]) for c in CAT_TITULO}}
    return s + sum(cats[c].get(v, 0.0) for c, v in vals.items())


muestra = te
dif = np.abs(np.array([predecir(r) for _, r in muestra.iterrows()]) - pipe.predict(muestra[COLS])).max()
assert dif < 1e-4, f"la fórmula exportada no coincide con el pipeline ({dif})"

res = te["log_precio"] - pipe.predict(te[COLS])
q05, q25, q75, q95 = np.quantile(res, [0.05, 0.25, 0.75, 0.95])  # mismos percentiles que el notebook 03
error_mediano = float(np.median(np.abs(np.exp(-res) - 1)) * 100)  # |predicho/real − 1|, como el 02

catalogo = {}
for (ma, mo, an), g in df.groupby(["marca", "modelo", "anio"]):
    catalogo.setdefault(ma, {}).setdefault(mo, {})[int(an)] = sorted(int(round(p)) for p in g["precio_usd"])
opciones = {c: sorted(df[c].astype(str).value_counts().loc[lambda s: s >= 20].index.tolist()) for c in CAT_TITULO}

salida = {
    "intercepto": float(reg.intercept_), "num": num, "pend_marca": pend_marca, "cats": cats, "anio_ref": 2026,
    "residuo_p05": float(q05), "residuo_p25": float(q25), "residuo_p75": float(q75), "residuo_p95": float(q95), "catalogo": catalogo, "opciones": opciones,
    "meta": {"avisos": int(len(df)), "train": int(len(tr)), "fecha": "2026-10-28", "modelo": "Ridge",
             "alpha": M["alpha"], "umbral": M["umbral"], "error_mediano_pct": round(error_mediano, 1)},
}
SALIDA.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"Exportado {SALIDA} · diferencia máxima con el pipeline: {dif:.2e}")
