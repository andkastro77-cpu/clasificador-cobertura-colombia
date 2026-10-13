"""Configuración general del clasificador de cobertura terrestre.

Aquí se definen los parámetros que puedes modificar sin tocar el resto
del código: zona de estudio, fechas, umbral de nubes y colores del mapa.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. ZONA DE ESTUDIO (municipios de Antioquia, Colombia)
# ---------------------------------------------------------------------------
MUNICIPIOS = ["Sabaneta", "Envigado"]
DEPARTAMENTO = "Antioquia"
PAIS = "Colombia"

# ---------------------------------------------------------------------------
# 2. PROYECTO DE GOOGLE CLOUD (obligatorio para Google Earth Engine)
#
#   Opción A (recomendada): define la variable de entorno EE_PROJECT_ID
#       Windows (PowerShell):  $env:EE_PROJECT_ID = "mi-proyecto"
#   Opción B: escribe el ID directamente entre comillas abajo.
# ---------------------------------------------------------------------------
PROYECTO_GEE = os.environ.get("EE_PROJECT_ID", "")

# ---------------------------------------------------------------------------
# 3. PARÁMETROS DE ANÁLISIS
# ---------------------------------------------------------------------------
# Ventana de fechas (formato AAAA-MM-DD). Dynamic World existe desde 2015.
FECHA_INICIO = "2025-01-01"
FECHA_FIN = "2026-10-01"

# Se ignoran escenas satelitales con más de este porcentaje de nubes.
MAX_NUBES = 30

# Resolución del ráster de salida en metros (Dynamic World nativo = 10 m).
ESCALA_M = 10

# Proyección del ráster exportado (UTM zona 18N, corresponde a Antioquia).
CRS_SALIDA = "EPSG:32618"

# ---------------------------------------------------------------------------
# 4. CARPETAS DE SALIDA
# ---------------------------------------------------------------------------
CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_SALIDA = CARPETA_PROYECTO / "salidas"

# ---------------------------------------------------------------------------
# 5. CLASES DE COBERTURA DE DYNAMIC WORLD
#   El número es el valor del píxel en la imagen clasificada.
#   'color' se usa tanto en el GeoTIFF como en el mapa PNG.
# ---------------------------------------------------------------------------
CLASES = {
    0: {"nombre": "Agua", "english": "water", "color": "#3D7BD6"},
    1: {"nombre": "Bosque / árboles", "english": "trees", "color": "#1B7A2E"},
    2: {"nombre": "Pastizales", "english": "grass", "color": "#9CCB65"},
    3: {"nombre": "Cultivos", "english": "crops", "color": "#E8E23C"},
    4: {"nombre": "Matorral", "english": "shrub_and_scrub", "color": "#B99A52"},
    5: {"nombre": "Área urbana", "english": "built", "color": "#A02020"},
    6: {"nombre": "Suelo desnudo", "english": "bare", "color": "#D2B48C"},
    7: {"nombre": "Nieve / hielo", "english": "snow_and_ice", "color": "#F2F2F2"},
    8: {"nombre": "Vegetación inundada", "english": "flooded_vegetation", "color": "#5FBFA8"},
}
