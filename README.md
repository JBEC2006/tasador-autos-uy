# Tasador de autos usados (Uruguay)

Proyecto académico de Machine Learning (Universidad de Montevideo): regresión para
predecir el precio de autos usados publicados en Mercado Libre Uruguay
(`autos.mercadolibre.com.uy`). El dataset es **una foto del mercado** (una sola
corrida), no un monitoreo.

## Estructura

```
scraper/     código del scraping
  client.py      cliente HTTP: robots.txt, pausas, tope de requests, corte ante bloqueos
  parse.py       extracción desde el JSON embebido en cada página
  pages.py       caché de páginas, progreso y logging
  feasibility.py Paso 0: prueba con una sola página
  discover.py    descubrimiento de marcas y modelos (filtros del propio sitio)
  plan.py        lista de búsquedas y estimación de requests (sin red)
  run.py         corrida de scraping
  summary.py     resumen del CSV (sin red)
  test_parse.py  test del parser con el HTML guardado
data/        autos_raw.csv, progress.json, scrape.log, discovery.json, busquedas.csv
data/raw/    HTML crudo (no se versiona)
notebooks/   01_limpieza_eda, 02_modelos (base, Ridge, Lasso, árbol), 03_residuos_depreciacion,
             preparar.py (variables, compartido por 02 y 03), exportar_tasador.py, figuras/
informe/     informe.tex (borrador del informe, en LaTeX)
presentacion/  Presentación 1 (propuesta inicial, primera entrega)
  defensa_final/    presentación de la defensa: presentacion.html (abrir con doble clic;
                    flechas o clic para avanzar, F pantalla completa, N muestra quién habla)
  defensa/project/  deck anterior de la defensa (una slide HTML por archivo)
  tasador/          tasador en vivo: tasador.html + modelo.json y modelo.js
                    (los genera notebooks/exportar_tasador.py a partir del notebook 02)
Proyecto.pdf   consigna del proyecto (solo local, no se versiona)
```

## Cómo correrlo

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

.venv\Scripts\python -m unittest scraper.test_parse -v   # test del parser (sin red)
.venv\Scripts\python -m scraper.discover                  # marcas y modelos
.venv\Scripts\python -m scraper.plan                      # lista de búsquedas (sin red)
.venv\Scripts\python -m scraper.run --max-busquedas 3     # prueba chica
.venv\Scripts\python -m scraper.run                       # corrida completa
.venv\Scripts\python -m scraper.summary                   # resumen del CSV (sin red)
```

### Análisis (sin red)

Los notebooks se corren en orden, desde `notebooks/` (usan rutas relativas `../data`):

```bash
cd notebooks
..\.venv\Scripts\python -m jupyter nbconvert --to notebook --execute --inplace 01_limpieza_eda.ipynb
..\.venv\Scripts\python -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 02_modelos.ipynb
..\.venv\Scripts\python -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 03_residuos_depreciacion.ipynb
..\.venv\Scripts\python exportar_tasador.py
```

| Paso | Entrada | Salida |
|---|---|---|
| `01_limpieza_eda` | `autos_raw.csv` | `autos_clean.csv`, `limpieza_reglas.csv`, figuras 01–03 |
| `02_modelos` | `autos_clean.csv` | `resultados_test.csv`, `predicciones_test.csv`, `mejor_modelo.json`, figura 06 |
| `03_residuos_depreciacion` | lo anterior | `extremos_revisar.csv`, figuras 04–05 |
| `exportar_tasador.py` | lo anterior | `presentacion/tasador/modelo.json` y `modelo.js` |

Los tres juntos tardan unos 10 minutos (lo más lento es Lasso con alpha chico, en el 02, y el bootstrap del 03).
Todo usa semilla 42: el split train/test es el mismo en el 02, el 03 y el exportador.

**Reanudar:** si la corrida se corta, se vuelve a lanzar el mismo comando. Cada
página descargada queda en `data/raw/pages/`; lo ya bajado se relee del disco sin
hacer requests, y el contador de requests persiste en `data/progress.json`.

## Fecha del scraping

- Prueba de factibilidad y descubrimiento: 2026-10-28.
- Corrida completa: 2026-10-28 (12:52 a 15:23, hora de Uruguay).
- Resultado: **17.095 avisos únicos** de 17.353 usados informados por el sitio
  (**98,5 % de cobertura**). Se usaron 1.487 requests de los 2.000 permitidos, sumando
  todo el proyecto: factibilidad, descubrimiento, prueba y corrida. No hubo
  bloqueos ni URLs prohibidas.

## Reglas respetadas

- **robots.txt:** se descarga el de `autos.`, `auto.`, `listado.` y `www.` de
  `mercadolibre.com.uy` y se verifica **cada URL** antes de pedirla. Como
  `urllib.robotparser` no interpreta comodines (`*`, `$`), se complementa con un
  chequeo propio de comodines (estilo Google: gana la regla más larga); una URL se
  pide solo si ambos la permiten. No se usan filtros prohibidos: paginación
  `_Desde_`, `_PriceRange_`, `_KILOMETERS_`, `_CarDealer_`, `_NoIndex_True`, etc.
  Los robots.txt no definen `Crawl-delay` para `User-agent: *`.
- **Ritmo:** un request a la vez, pausa aleatoria de 4 a 8 s, tope total de
  2.000 requests en todo el proyecto (la corrida frena sola a 50 del tope).
- **Sin evasión:** User-Agent de navegador fijo, sin proxies ni rotación de IP,
  sin navegador automatizado, sin login, sin resolver captchas. No se usa la API
  de Mercado Libre.
- **Corte ante bloqueos:** ante 403, 429, captcha o redirección a
  verificación de cuenta, espera 60 s y reintenta una vez; si se repite, guarda
  el progreso y frena.
- **Sin datos personales:** no se guardan nombres, teléfonos, emails ni nicknames.
  Del vendedor solo se guarda el tipo (particular/concesionaria) y si es tienda
  oficial (sí/no); el nombre del comercio que aparece en tiendas oficiales se descarta.
- **Uso de asistentes de IA:** los robots.txt del sitio excluyen explícitamente a
  agentes de IA (`ClaudeBot`, `Claude-User`, `GPTBot`, etc.). Por eso el código se
  escribió con ayuda de un asistente, pero **todos los requests al sitio los ejecutó
  el autor** desde su terminal; el asistente solo trabajó con el HTML ya guardado.

## Cómo se partieron las búsquedas

Solo se pide la **primera página** de cada búsqueda (48 avisos como máximo), porque
la paginación está prohibida por robots.txt. Para cubrir el mercado se parte en
búsquedas más chicas, usando siempre los links de filtros que publica el sitio:

1. Filtro **Usado** (`/usado/`, permitido): 17.353 avisos de 23.098.
2. **Marca × tipo de vendedor** (`/chevrolet/usado/dueno/`, `/.../concesionaria/`):
   así se obtiene `tipo_vendedor` sin visitar cada aviso.
3. Si tiene más de 48 avisos: **× modelo**.
4. Si sigue con más de 48: **× rango de año**, agrupando años consecutivos con los
   conteos por año que informa el sitio y su plantilla de URL (`/$from-$to/`).

Las búsquedas se procesan de mayor a menor, así si la guardia de presupuesto corta,
lo que queda afuera es la cola larga (modelos con 1–2 avisos). Para cada búsqueda
el log y `data/busquedas.csv` registran el total informado por el sitio y los avisos
obtenidos, para calcular la cobertura.

## Columnas de `data/autos_raw.csv`

`item_id, url, titulo, marca, modelo, modelo_origen, version, anio, km, precio,
moneda, barrio, departamento, tipo_vendedor, tienda_oficial, transmision_titulo,
combustible_titulo, motor_titulo, busqueda_origen, fecha_scraping, flag`

- `precio` es numérico y `moneda` va aparte (USD/UYU), **sin convertir**.
- `modelo_origen`: `busqueda` si el modelo lo fijó la búsqueda; `titulo` si se
  dedujo del título contra la lista de modelos del sitio.
- `version`: lo que queda del título después de marca, modelo y año.
- `transmision_titulo`, `combustible_titulo`, `motor_titulo`: indicios tomados
  del título (AT/MT/manual/automático; diésel/nafta/híbrido/eléctrico; cilindrada
  tipo "1.6"). Vacíos si el título no dice nada o es ambiguo.
- `flag` (no se elimina ninguna fila): `km_0`, `km_menor_1000`,
  `anio_actual_o_posterior`, `sin_precio`, `sin_anio`, `sin_km`.
- Deduplicado por `item_id`; si un aviso aparece en varias búsquedas, queda la
  más específica.

## Limitaciones

- Solo primera página por búsqueda: un **año individual** con más de 48 avisos
  para un modelo y tipo de vendedor queda con cobertura parcial; se registra en el
  log. En la corrida pasó 2 veces: Chevrolet Montana 2024 de concesionaria (50
  avisos) y Chevrolet Onix 2023 de concesionaria (49 avisos).
- Avisos que el sitio no incluye en el filtro de modelo (45 búsquedas
  marca × vendedor los tienen) solo se ven si entran en la primera página de la
  marca.
- La suma de avisos por marca (17.298) es algo menor al total informado (17.353):
  ~55 avisos sin marca en el filtro no se pueden alcanzar por esta vía.
- 35 marcas mínimas (58 avisos) no ofrecen filtro de vendedor: `tipo_vendedor` vacío.
- Una marca ("Americano") devolvió una página sin datos.
- Combustible, transmisión, carrocería y motor exactos solo están en la página de
  detalle de cada aviso; con un request por aviso se superaría el tope de 2.000,
  así que esa fase no se corrió y se usan los indicios del título.
- Hay valores cargados mal por los vendedores, que se mantienen tal cual para
  tratarlos en la limpieza. Algunos ejemplos son km de relleno (9.999.999), precios
  en USD de 99.999.999 o de 500, y precios en UYU de 1.000.000.000.
- El orden "más relevantes" del sitio decide qué 48 avisos se ven cuando una
  búsqueda tiene más: no es una muestra aleatoria.
