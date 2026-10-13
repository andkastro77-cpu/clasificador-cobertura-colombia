"""Muestra el ráster GeoTIFF en pantalla (alternativa a QGIS).

Uso:
    python ver_raster.py

Útil cuando no tienes QGIS instalado y quieres inspeccionar el resultado
georreferenciado rápidamente desde el mismo proyecto.
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import rasterio

import config


def main() -> None:
    ruta = config.CARPETA_SALIDA / "cobertura_sabaneta_envigado.tif"
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}. Ejecuta primero: python main.py")

    with rasterio.open(ruta) as src:
        datos = src.read(1)
        transform = src.transform
        limites = src.bounds
        print(f"Dimensiones : {src.width} x {src.height} px")
        print(f"Resolución  : {config.ESCALA_M} m/píxel")
        print(f"Proyección  : {src.crs}")
        print(f"Extensión   : {limites}")

    colores = [config.CLASES[c]["color"] for c in sorted(config.CLASES)]
    cmap = ListedColormap(colores)
    norm = BoundaryNorm([c - 0.5 for c in range(len(colores) + 1)], cmap.N)

    fig, ax = plt.subplots(figsize=(11, 10))
    ax.imshow(
        datos,
        cmap=cmap,
        norm=norm,
        interpolation="nearest",
        extent=(limites.left, limites.right, limites.bottom, limites.top),
    )
    ax.set_title(
        "Ráster GeoTIFF — cobertura terrestre (Envigado y Sabaneta)",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_xlabel("Este (m) · UTM 18N")
    ax.set_ylabel("Norte (m) · UTM 18N")

    leyenda = [
        plt.Rectangle((0, 0), 1, 1, facecolor=config.CLASES[c]["color"])
        for c in sorted(config.CLASES)
    ]
    ax.legend(
        leyenda,
        [config.CLASES[c]["nombre"] for c in sorted(config.CLASES)],
        loc="lower left",
        fontsize=9,
        framealpha=0.9,
    )

    plt.tight_layout()
    plt.show()
    print("Cierra la ventana del gráfico para terminar.")


if __name__ == "__main__":
    main()
