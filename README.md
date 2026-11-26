<p align="center">
  <a href="https://flashout.net">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/flashout-labs-dark.svg">
      <img src="docs/flashout-labs-light.svg" alt="Flashout Labs" width="220">
    </picture>
  </a>
</p>

# PostalCR API

API JSON gratuita con las **7 provincias, 84 cantones y 494 distritos de Costa Rica**, su **código postal oficial** y si están dentro de la **Gran Área Metropolitana (GAM)**. Datos de la División Territorial Administrativa (**DTA 2026**) del Instituto Geográfico Nacional.

**Base URL:** `https://api.postalcr.dev` · **Documentación:** [postalcr.dev/api](https://postalcr.dev/api/) · **Buscador:** [postalcr.dev](https://postalcr.dev)

- Sin API key, sin registro, sin límites. CORS abierto: funciona desde el navegador, una app o un servidor.
- Archivos estáticos en la red de Cloudflare: rápidos desde cualquier país.
- Cada distrito trae el enlace a su página en [postalcr.dev](https://postalcr.dev), para mostrarle a tus usuarios dónde queda.

## El código postal de Costa Rica

Son 5 dígitos y equivalen al código oficial del distrito: **provincia** (1 dígito) + **cantón** (2) + **distrito** (2).

```
1 03 05  →  San José · Desamparados · San Antonio  →  10305
```

Tratá los códigos como texto, no como números, para no perder ceros.

## Rutas

| Ruta | Devuelve |
|---|---|
| `/provincias.json` | Las 7 provincias, con área y cantidad de cantones y distritos |
| `/provincias/{provincia}.json` | Una provincia (`1`–`7`) y sus cantones |
| `/cantones.json` | Los 84 cantones con su provincia |
| `/cantones/{canton}.json` | Un cantón (código de 3 dígitos, `103`) y sus distritos |
| `/distritos.json` | Los 494 distritos con todos sus campos |
| `/distritos/{codigoPostal}.json` | Un distrito por su código postal (`10305`) |
| `/pueblos.json` | 6 891 pueblos y playas oficiales (Tamarindo, Santa Teresa…) con su distrito y código postal |
| `/distritos.geojson` | Contorno simplificado de los 494 distritos (GeoJSON), para dibujar mapas |
| `/gam.json` | Códigos postales dentro y fuera de la GAM, con la definición y el criterio |
| `/todo.json` | Árbol completo provincias → cantones → distritos |
| `/meta.json` | Versión, edición de la DTA, totales y fuentes |
| `/openapi.json` | Especificación OpenAPI 3.1 |
| `/llms.txt` | Guía para agentes de IA |

Un código que no existe responde `404`.

## Ejemplos

```js
const distrito = await fetch('https://api.postalcr.dev/distritos/10305.json').then(r => r.json());
```

```json
{
  "codigo_postal": "10305",
  "nombre": "San Antonio",
  "canton": { "codigo": "103", "nombre": "Desamparados" },
  "provincia": { "codigo": "1", "nombre": "San José" },
  "etiqueta": "San Antonio, Desamparados, San José",
  "area_km2": 2.1,
  "gam": true,
  "centro": [9.89899, -84.04652],
  "vecinos": ["10106", "10301", "10310", "10312", "11804", "30308"],
  "pueblos": ["San Antonio"],
  "url": "https://postalcr.dev/san-jose/desamparados/san-antonio/"
}
```

Selectores en cascada para un formulario de dirección:

```js
const API = 'https://api.postalcr.dev';
const provincias = await fetch(`${API}/provincias.json`).then(r => r.json());          // [{ codigo: "1", nombre: "San José", … }]
const { cantones } = await fetch(`${API}/provincias/1.json`).then(r => r.json());     // [{ codigo: "101", … }]
const { distritos } = await fetch(`${API}/cantones/103.json`).then(r => r.json());    // [{ codigo_postal: "10301", … }]
```

¿Envíos con tarifa distinta dentro y fuera de la GAM?

```js
const { gam } = await fetch('https://api.postalcr.dev/gam.json').then(r => r.json());
const esGam = new Set(gam).has(codigoPostal);
```

¿El usuario escribe un pueblo o una playa en vez del distrito? `/pueblos.json` trae 6 891 lugares oficiales (pueblos, caseríos, cabeceras de distrito, territorios indígenas y playas) con su distrito y código postal:

```json
{
  "nombre": "Santa Teresa",
  "tipo": "pueblo",
  "categoria": "Poblado",
  "alias": [],
  "codigo_postal": "60111",
  "distrito": "Cóbano",
  "canton": "Puntarenas",
  "provincia": "Puntarenas",
  "coordenadas": [9.64359, -85.16467],
  "url": "https://postalcr.dev/lugares/santa-teresa-cobano/"
}
```

Muchos nombres se repiten (hay 54 San Rafael): identificá un lugar por `nombre` + `codigo_postal`, nunca solo por el nombre. `categoria` es `Playa`, `Cabecera de distrito`, `Poblado`, `Caserío` o `Territorio/Comunidad indígena`; los caseríos enlazan a la página de su distrito.

Para buscar por nombre, descargá `/distritos.json` una vez (unos 50 KB comprimido) y filtrá en el cliente.

## Fuentes

- **Provincias, cantones, distritos y códigos:** [DTA 2026](https://www.snitcr.go.cr/biblioteca_DTA_menu), Instituto Geográfico Nacional (IGN), Registro Nacional. Las correcciones a la tabla del IGN están documentadas en [`data/correcciones.json`](data/correcciones.json).
- **Contornos, centro y vecinos:** límites distritales 1:5 000 del IGN (`IGN_5_CO:limitedistrital_5k`). `vecinos` son los distritos que comparten al menos 20 m de límite; `centro` es un punto dentro del distrito. Se regeneran con `scripts/generar_geo.py`.
- **GAM:** Plan GAM 2013-2030 (Decreto Ejecutivo 38334, MIVAH), cruzado con los límites distritales del IGN. Criterio y fuentes en [`data/gam.json`](data/gam.json).
- **Pueblos y playas:** localidades de referencia del INEC (Marco Geoestadístico Nacional) y accidentes costeros del IGN (playas). Cada punto se cruza con los polígonos distritales oficiales del IGN (DTA 2026) para obtener su distrito: el código no se copia de la fuente. Fuentes, método y advertencias en [`data/pueblos.json`](data/pueblos.json); se regenera con `scripts/generar_pueblos.py`.

## Versiones

La API sigue [semver](https://semver.org/lang/es/): la versión vigente está en `/meta.json` y los cambios en el [CHANGELOG](CHANGELOG.md). Las rutas de la v1 siguen respondiendo con una redirección a su equivalente en la v2.

## ¿Encontraste un error?

Abrí un [issue](https://github.com/ryze-cr/postalcr-api/issues/new/choose) con la fuente oficial. Detalles en [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencia

Código bajo licencia [MIT](LICENSE). Los datos provienen de instituciones públicas de Costa Rica.

---

**PostalCR** es un proyecto de [Flashout Labs](https://flashout.net), una línea de Flashout. Hecho para operar.

## English

Free JSON API with every Costa Rica province, canton and district and its official 5-digit postal code (IGN DTA 2026), plus whether it lies inside the Greater Metropolitan Area (GAM). No API key, open CORS. Base URL `https://api.postalcr.dev`; docs at [postalcr.dev/en/api](https://postalcr.dev/en/api/). Field names are in Spanish (`codigo_postal`, `nombre`, `canton`, `provincia`). Place names are kept exactly as the IGN publishes them.
