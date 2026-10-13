# Librerías incrustadas (vendored)

Archivos de **Leaflet**, la librería de mapas usada por `comparar.py` para
generar `salidas/comparacion.html`.

Se guardan aquí para que el HTML final quede **autocontenido**: las
librerías se leen de esta carpeta y se incrustan dentro del archivo, así
el visor funciona sin conexión a internet (solo el mapa base de calles
necesita red).

| Archivo | Versión | Origen |
|---|---|---|
| `leaflet.js` | 1.9.4 | https://unpkg.com/leaflet@1.9.4/dist/leaflet.js |
| `leaflet.css` | 1.9.4 | https://unpkg.com/leaflet@1.9.4/dist/leaflet.css |

**Licencia:** Leaflet es de código abierto bajo licencia **MIT**
(© 2010–2024 Vladimir Agafonkin, 2010-2024 CloudMade).

El comparador deslizante ("swipe") **no** usa un plugin externo: está
implementado directamente en `comparar.py` con CSS `clip-path`, por lo que
no hay dependencias adicionales.

**No editar** estos archivos: se perderían los cambios si se vuelven a
descargar desde el CDN.
