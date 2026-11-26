# Política de seguridad

La API es un conjunto de archivos estáticos de solo lectura: no tiene cuentas, formularios, base de datos ni código que corra en el servidor. Aun así, los reportes de seguridad son bienvenidos.

## Qué reportar

- Una forma de alterar los datos publicados sin pasar por el repositorio.
- Headers (CORS, caché) que expongan a quienes usan la API.
- Cambios maliciosos en el repositorio o en el flujo de publicación.

Un error en los datos no es un problema de seguridad: reportalo como [issue](https://github.com/ryze-cr/postalcr-api/issues/new/choose).

## Cómo reportar

No abras un issue público. Usá el reporte privado de GitHub: **[Reportar una vulnerabilidad](https://github.com/ryze-cr/postalcr-api/security/advisories/new)**. Incluí qué encontraste, cómo reproducirlo y su impacto. Se responde en un plazo de 7 días.

Solo se mantiene la versión publicada desde `main`.
