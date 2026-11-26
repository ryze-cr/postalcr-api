# Cambios

La API sigue [semver](https://semver.org/lang/es/). La versión vigente está en [`/meta.json`](https://api.postalcr.dev/meta.json).

## 2.0.0 — 2026-11

Primera versión de **PostalCR API** en `https://api.postalcr.dev`, con un diseño de rutas nuevo.

### Nuevo

- Rutas por recurso: `/provincias/{provincia}.json`, `/cantones.json`, `/cantones/{canton}.json` y `/distritos/{codigoPostal}.json`.
- `/pueblos.json`: 6 891 lugares oficiales que no son distritos (pueblos, caseríos, cabeceras de distrito, territorios indígenas y playas, del INEC y el IGN), cada uno con su distrito y código postal calculados sobre los límites oficiales del IGN.
- Cada distrito trae `etiqueta` (por ejemplo, «San Antonio, Desamparados, San José»), `centro`, `vecinos`, `pueblos` y `url` (su página en postalcr.dev).
- `/distritos.geojson`: contorno simplificado de los 494 distritos, desde los límites del IGN. Se simplifican como una cobertura: dos distritos vecinos comparten exactamente el mismo borde, sin huecos ni solapes entre ellos.
- `/meta.json` lista todas las fuentes oficiales con su edición.

### Cambios que rompen integraciones

- Los códigos son siempre strings con todos sus dígitos: provincia `"1"`, cantón `"103"`, distrito `"10305"`.
- Las listas son arreglos de objetos en lugar de objetos `{ "número": "nombre" }`.
- En un distrito, `canton` y `provincia` son objetos `{ codigo, nombre }` y el nombre del distrito está en `nombre`.

### Rutas anteriores

Las rutas anteriores redirigen (301) a su equivalente en la v2. La forma de la respuesta es la de la v2.

| Antes | Ahora |
|---|---|
| `/provincia/{p}/cantones.json` | `/provincias/{p}.json` |
| `/provincia/{p}/canton/{c}/distritos.json` | `/cantones/{PCC}.json` (por ejemplo, `/provincia/1/canton/3/` → `/cantones/103.json`) |
| `/codigo-postal/{PCCDD}.json` | `/distritos/{PCCDD}.json` |
