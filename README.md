# Clasificador de Cobertura Terrestre — Envigado y Sabaneta 🇨🇴

Programa en Python que detecta el **tipo de cobertura terrestre** (bosque,
cultivos, área urbana, agua, etc.) de los municipios de **Envigado** y
**Sabaneta** (Antioquia, Colombia) usando **modelos de inteligencia
artificial de código abierto**.

## ¿Cómo funciona?

| Componente | Tecnología |
|---|---|
| Imágenes de entrada | **Sentinel-2** (Agencia Espacial Europea, resolución 10 m) |
| Modelo de IA | **Dynamic World** ([dynamicworld.app](https://dynamicworld.app)) — red neuronal de código abierto de Google + WRI |
| Plataforma de cómputo | **Google Earth Engine** (todo el procesamiento ocurre en la nube; tu PC no necesita GPU) |
| Límites administrativos | Colección **FAO/GAUL 2015** disponible en Earth Engine |

El modelo clasifica **cada píxel** de la imagen en una de 9 clases de
cobertura, promediando la probabilidad a lo largo de todas las escenas
sin nubes del período de análisis.

### Clases de cobertura

| # | Clase | Color en el mapa |
|---|---|---|
| 0 | Agua | 🔵 Azul |
| 1 | Bosque / árboles | 🟢 Verde oscuro |
| 2 | Pastizales | 🟩 Verde claro |
| 3 | Cultivos | 🟡 Amarillo |
| 4 | Matorral | 🟤 Beige |
| 5 | Área urbana | 🔴 Rojo |
| 6 | Suelo desnudo | 🟫 Arena |
| 7 | Nieve / hielo | ⚪ Blanco |
| 8 | Vegetación inundada | 🟦 Turquesa |

## Requisitos

- Python 3.10 o superior
- Cuenta de Google **con Earth Engine aprobada**: https://earthengine.google.com/
- Un proyecto de Google Cloud con la **API de Earth Engine habilitada**

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/andkastro77-cpu/clasificador-cobertura-colombia.git
cd clasificador-cobertura-colombia

# 2. Crear entorno virtual e instalar dependencias
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 3. Configurar el proyecto de Google Cloud
$env:EE_PROJECT_ID = "tu-proyecto"   # PowerShell
# export EE_PROJECT_ID="tu-proyecto"  # Linux/macOS
```

La **primera ejecución** abrirá el navegador para autorizar tu cuenta de
Earth Engine (solo se hace una vez).

## Uso

```bash
python main.py
```

## Salidas

Los resultados se guardan en la carpeta `salidas/`:

- **`mapa_cobertura_sabaneta_envigado.png`** — mapa temático con leyenda y límites municipales
- **`estadisticas_sabaneta_envigado.csv`** — porcentaje de superficie por tipo de cobertura
- **`cobertura_sabaneta_envigado.tif`** — ráster georreferenciado (compatible con QGIS)

## Estructura del proyecto

```
clasificador-cobertura-colombia/
├── config.py      # Parámetros: municipios, fechas, nubes, clases y colores
├── auth.py        # Autenticación con Google Earth Engine
├── zonas.py       # Límites de Sabaneta y Envigado (FAO/GAUL)
├── clasificar.py  # Motor: Sentinel-2 + Dynamic World
├── reporte.py     # Mapa PNG, estadísticas CSV y descarga GeoTIFF
├── main.py        # Orquestador del flujo completo
├── requirements.txt
└── salidas/       # Resultados generados
```

## Configuración

Todo se ajusta en **`config.py`**:

- `MUNICIPIOS` — cambiar la zona de estudio
- `FECHA_INICIO` / `FECHA_FIN` — período de análisis
- `MAX_NUBES` — umbral de nubes por escena (%)
- `ESCALA_M` — resolución del ráster de salida

## Licencia

MIT — libre para uso académico y personal.
