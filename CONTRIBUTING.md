# Cómo contribuir

## Reportar un error en los datos

Abrí un [issue](https://github.com/ryze-cr/postalcr-api/issues/new/choose) con:

- El código postal o la ruta afectada (por ejemplo, `10305` o `/distritos/10305.json`).
- Qué dice la API y qué debería decir.
- La fuente oficial: la tabla de la DTA del IGN, una ley o un decreto publicado en La Gaceta.

Si el error es sobre la GAM, indicá el distrito y por qué; la clasificación y sus fuentes están en `data/gam.json`. Si es sobre un pueblo o una playa, indicá la fuente que lo ubica en otro distrito.

## Proponer un cambio

1. Hacé un fork y una rama.
2. Los datos viven en `data/`. No edites `public/` a mano: se genera.
   - Una ley que crea o cambia un distrito y todavía no está en la DTA va en `data/correcciones.json`, con su motivo; después corré `scripts/extraer_dta.py`.
3. Corré `python3 scripts/generar_api.py` y `python3 scripts/validar.py`.
4. Abrí un PR. La validación automática tiene que pasar para hacer el merge.

## Nueva edición de la DTA

El IGN publica una edición nueva cada dos años en [snitcr.go.cr](https://www.snitcr.go.cr/biblioteca_DTA_menu):

1. `pip install -r scripts/requirements.txt`
2. `python3 scripts/extraer_dta.py <PDF> --edicion <año> --url <url del PDF>`
3. Clasificá en `data/gam.json` los distritos nuevos (`validar.py` avisa cuáles faltan).
4. Actualizá la edición en el README y subí `VERSION` en `scripts/generar_api.py` (menor si solo cambian datos), con su entrada en `CHANGELOG.md`.
5. `python3 scripts/generar_api.py && python3 scripts/validar.py`
6. Después del merge, publicá el release en GitHub con esa versión.
