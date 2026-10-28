"""Resumen rápido de data/autos_raw.csv (Paso 4). No hace requests.

Uso: python -m scraper.summary
"""
import pandas as pd

from scraper.run import CSV_FILE

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 40)


def main():
    df = pd.read_csv(CSV_FILE)
    print(f"Filas: {len(df)}  |  item_id únicos: {df['item_id'].nunique()}\n")
    print("=== 10 filas de ejemplo ===")
    print(df.sample(min(10, len(df)), random_state=0)[
        ["item_id", "marca", "modelo", "modelo_origen", "version", "anio", "km", "precio", "moneda",
         "barrio", "departamento", "tipo_vendedor", "transmision_titulo", "combustible_titulo", "flag"]
    ].to_string(index=False))
    print("\n=== Nulos por columna ===")
    nulls = df.isna().sum()
    print(pd.DataFrame({"nulos": nulls, "%": (100 * nulls / len(df)).round(1)}).to_string())
    print("\n=== Rangos ===")
    for col in ("anio", "km"):
        print(f"{col:6s} min {df[col].min():>12,.0f}   mediana {df[col].median():>12,.0f}   max {df[col].max():>12,.0f}")
    for moneda, g in df.groupby("moneda"):
        p = g["precio"]
        print(f"precio {moneda}: n={len(g)}  min {p.min():,.0f}   mediana {p.median():,.0f}   max {p.max():,.0f}")
    print("\n=== Conteos ===")
    for col in ("tipo_vendedor", "modelo_origen", "transmision_titulo", "combustible_titulo", "flag"):
        print(f"{col}: {df[col].value_counts(dropna=False).to_dict()}")


if __name__ == "__main__":
    main()
