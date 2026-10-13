"""Programa principal: detecta la cobertura terrestre de Envigado y Sabaneta.

Ejecución:
    python main.py

Flujo:
    1. Conecta a Google Earth Engine
    2. Descarga los límites de los dos municipios
    3. Clasifica con Dynamic World (Sentinel-2, 10 m)
    4. Calcula estadísticas (% por tipo de cobertura)
    5. Guarda mapa PNG, estadísticas CSV y ráster GeoTIFF en ./salidas/
"""

import sys
from pathlib import Path

# La consola de Windows usa cp1252 por defecto y no soporta flechas ni
# acentos: forzamos UTF-8 para que la salida se vea bien.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
import auth
import zonas
import clasificar
import reporte


def main() -> None:
    print("=" * 60)
    print("CLASIFICADOR DE COBERTURA TERRESTRE — COLOMBIA")
    print(f"Zona: {', '.join(config.MUNICIPIOS)} ({config.DEPARTAMENTO})")
    print(f"Período: {config.FECHA_INICIO} → {config.FECHA_FIN}")
    print("=" * 60)

    # 1. Conexión ---------------------------------------------------------
    auth.conectar()
    import ee  # noqa: E402  (ya inicializado por auth)

    # 2. Zona de estudio --------------------------------------------------
    municipios = zonas.obtener_municipios()
    geometria = zonas.geometria_unida(municipios)

    # 3. Clasificación ----------------------------------------------------
    imagen = clasificar.clasificar(geometria)

    # 4. Estadísticas -----------------------------------------------------
    porcentajes = clasificar.estadisticas_servidor(imagen, geometria)
    tabla = reporte.tabla_estadisticas(porcentajes)

    # 5. Salidas ----------------------------------------------------------
    config.CARPETA_SALIDA.mkdir(exist_ok=True)

    nombre = "sabaneta_envigado"
    ruta_csv = config.CARPETA_SALIDA / f"estadisticas_{nombre}.csv"
    ruta_png = config.CARPETA_SALIDA / f"mapa_cobertura_{nombre}.png"
    ruta_tif = config.CARPETA_SALIDA / f"cobertura_{nombre}.tif"

    tabla.to_csv(ruta_csv, index=False, encoding="utf-8-sig")
    print(f"[OK] Estadísticas guardadas: {ruta_csv.name}")

    # El ráster se descarga antes de graficar: el mapa se dibuja leyendo
    # ese GeoTIFF, así mapa y estadísticas siempre muestran lo mismo.
    reporte.descargar_raster(imagen, geometria, ruta_tif)

    gdf = zonas.a_geodataframe(municipios)
    reporte.graficar_mapa(ruta_tif, gdf, porcentajes, ruta_png)

    # Resumen en consola --------------------------------------------------
    print("\n--- RESULTADO (% de superficie) ---")
    print(tabla.to_string(index=False))
    print(f"\nArchivos en: {config.CARPETA_SALIDA}")
    print(Path(__file__).name, "→ terminado ✔")


if __name__ == "__main__":
    main()
