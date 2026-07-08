# Guía de instalación RuView para hoteles

> **Objetivo:** Saber si hay alguien dentro de una habitación **sin cámaras, sin tocar la puerta y sin molestar al huésped**, usando señales WiFi (CSI) para detectar presencia u ocupación.

Repositorio clonado: [ruvnet/RuView](https://github.com/ruvnet/RuView)

---

## ¿Qué hace RuView en un hotel?

RuView (WiFi DensePose) convierte las ondas WiFi en un sensor de **presencia y ocupación**. Cuando una persona se mueve, respira o simplemente está sentada, altera las señales de radio de forma medible.

Para limpieza de habitaciones, lo que te interesa es:

| Función | Para qué sirve en el hotel |
|---------|----------------------------|
| **Detección de presencia** | Saber si la habitación está vacía o ocupada |
| **Ocupación por zona** | Confirmar si hay alguien en la cama, baño o zona de estar |
| **Módulo `meeting-room`** | Indicador “libre / ocupada” por habitación (pensado para salas, aplicable a habitaciones) |
| **Módulo `occupancy-zones`** | Conteo de personas por zona, incluso a través de paredes internas |

**Ventajas frente a cámaras o sensores en la puerta:**

- Sin video → más privacidad (no graba imágenes)
- Funciona con la luz apagada y con la persona durmiendo
- No requiere que el huésped abra la puerta ni lleve ningún dispositivo
- El WiFi del hotel ya ilumina la habitación con ondas de radio

**Limitaciones importantes (léelas antes de comprar):**

- Software en **beta**: APIs y firmware pueden cambiar
- **No uses ESP32 original ni ESP32-C3** — solo **ESP32-S3**
- Con **1 solo sensor** la precisión es limitada; se recomiendan **2+ nodos por habitación**
- No es un sistema médico ni certificado para seguridad crítica
- La detección funciona mejor con personas **quietas o durmiendo** que con mucho ruido RF (microondas, muchos APs, obras)

---

## Arquitectura recomendada para un hotel

```
┌─────────────────────────────────────────────────────────────┐
│  Habitación 101                                              │
│  ┌──────────┐         WiFi del hotel        ┌──────────┐   │
│  │ ESP32-S3 │◄──────────────────────────────►│ Router   │   │
│  │ (sensor) │   ondas CSI / presencia        │ / AP     │   │
│  └────┬─────┘                                └──────────┘   │
│       │ UDP (datos de presencia)                             │
└───────┼─────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────┐     ┌─────────────────────────────┐
│ PC / Raspberry Pi │────►│ Panel web / app limpieza    │
│ (sensing-server)  │     │ "101: OCUPADA / LIBRE"      │
└───────────────────┘     └─────────────────────────────┘
```

**Por habitación (recomendado):**

- **1–2× ESP32-S3** ocultos en el techo, detrás del mueble TV o en el pasillo técnico
- Conexión al **WiFi de la habitación** (SSID de huéspedes o red IoT separada)
- Un **servidor central** (PC del hotel o Raspberry Pi) que recibe todos los sensores

---

## Lista de compras (qué piezas necesitas)

### Opción A — Piloto (1 habitación de prueba)

Ideal para probar antes de escalar.

| Pieza | Cantidad | Precio aprox. | Dónde comprarla | Notas |
|-------|----------|---------------|-----------------|-------|
| **ESP32-S3 DevKitC-1** (8 MB flash) | 2 | ~8–12 € c/u | Amazon, AliExpress, Mouser, Espressif | **Obligatorio: chip ESP32-S3**, no C3 ni ESP32 clásico |
| **Cable USB-C** (datos, no solo carga) | 1 | ~5 € | Cualquier tienda | Para flashear firmware la primera vez |
| **PC con Windows 10/11** | 1 | (ya lo tienes) | — | 8 GB RAM recomendado |
| **Router/AP WiFi** en la habitación | 1 | (ya en el hotel) | — | Red 2.4 GHz estable |
| **Raspberry Pi 4/5** (opcional) | 1 | ~60–80 € | — | Si quieres servidor 24/7 sin depender de un PC |

**Total piloto:** ~25–30 € en sensores + PC existente.

---

### Opción B — Producción (por habitación)

| Pieza | Cantidad / habitación | Precio aprox. | Notas |
|-------|----------------------|---------------|-------|
| ESP32-S3 (8 MB) | 2 | ~16–24 € | Mejor cobertura: uno cerca de cama, otro cerca de baño |
| Fuente USB 5 V permanente | 2 | ~6 € c/u | Alimentación continua del sensor |
| Caja/carcasa discreta | 2 | ~3 € c/u | Montaje en techo o mueble |
| Servidor central compartido | 1 por hotel | ~80–150 € | Raspberry Pi 5 o mini PC |

**Ejemplo 20 habitaciones:** ~40 sensores ≈ 320–480 € + 1 servidor central.

---

### Opción C — Sistema completo con Cognitum Seed (avanzado)

Para muchas habitaciones, historial, módulos extra (`meeting-room`, `energy-audit`, etc.):

| Pieza | Cantidad | Precio aprox. | Notas |
|-------|----------|---------------|-------|
| ESP32-S3 mesh | 3–6 por zona grande | ~54 € (3 nodos) | Multistatic mesh, mayor precisión |
| [Cognitum Seed](https://cognitum.one) | 1 por planta o bloque | ~140 € total (Seed + ESP32) | Memoria persistente, catálogo de 105 módulos edge |
| Tailscale (opcional) | — | Gratis | Acceso remoto seguro al panel |

---

### Piezas que NO sirven

| Pieza | Motivo |
|-------|--------|
| ESP32 (original) | Un solo núcleo, insuficiente para CSI |
| ESP32-C3 | Un solo núcleo, no soportado |
| Solo un portátil con WiFi | Solo RSSI (presencia muy básica, sin CSI completo) |
| Cámaras IP | RuView no las usa; son otro sistema |

---

## Requisitos de software

| Requisito | Mínimo | Recomendado |
|-----------|--------|-------------|
| SO | Windows 10/11, Linux, macOS | Windows 11 o Ubuntu 22.04 |
| RAM | 4 GB | 8 GB+ |
| Disco | 2 GB libres | 5 GB+ |
| Docker Desktop | 20+ | 24+ (forma más fácil en Windows) |
| Python | 3.10+ | 3.13+ (para flashear ESP32) |
| Rust | 1.70+ | 1.85+ (solo si compilas desde código) |

---

## Instalación paso a paso (Windows)

### Paso 1 — Probar sin hardware (demo en 30 segundos)

Verifica que el software funciona antes de comprar sensores:

```powershell
docker pull ruvnet/wifi-densepose:latest
docker run -p 3000:3000 ruvnet/wifi-densepose:latest
```

Abre en el navegador: **http://localhost:3000**

Verás datos **simulados** (no reales). Sirve para conocer el panel y la API.

---

### Paso 2 — Instalar Python (para flashear los ESP32)

```powershell
pip install esptool pyserial
```

Instala también el **driver CP210x** si Windows no detecta el ESP32:  
https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers

---

### Paso 3 — Flashear firmware en cada ESP32-S3

Los binarios precompilados están en el repo clonado:

```
firmware/esp32-csi-node/release_bins/
```

Conecta el ESP32 por USB. En el Administrador de dispositivos anota el puerto (ej. `COM7`).

**Placa con 8 MB flash (la más común):**

```powershell
cd c:\Users\jejej\OneDrive\Escritorio\github_projects\ruview

python -m esptool --chip esp32s3 --port COM7 --baud 460800 `
  write_flash --flash_mode dio --flash_size 8MB `
  0x0     firmware/esp32-csi-node/release_bins/bootloader.bin `
  0x8000  firmware/esp32-csi-node/release_bins/partition-table.bin `
  0xf000  firmware/esp32-csi-node/release_bins/ota_data_initial.bin `
  0x20000 firmware/esp32-csi-node/release_bins/esp32-csi-node.bin
```

> Cambia `COM7` por tu puerto real. Si tienes placa **4 MB** (ej. ESP32-S3 SuperMini), usa los binarios `*-4mb.bin` y `--flash_size 4MB`.

---

### Paso 4 — Configurar WiFi del sensor (provision)

Cada ESP32 debe unirse al WiFi del hotel y enviar datos al servidor central.

1. Averigua la **IP del PC/servidor** donde correrá RuView (ej. `192.168.1.50`)
2. Ejecuta:

```powershell
python firmware/esp32-csi-node/provision.py --port COM7 `
  --ssid "WiFi-Hotel-Piso2" `
  --password "tu_contraseña_wifi" `
  --target-ip 192.168.1.50 `
  --target-port 5005 `
  --node-id 101 `
  --edge-tier 2
```

| Parámetro | Qué hace |
|-----------|----------|
| `--ssid` / `--password` | WiFi de la habitación o red IoT del hotel |
| `--target-ip` | IP del servidor RuView |
| `--node-id` | Identificador único (usa número de habitación, ej. 101, 102…) |
| `--edge-tier 2` | Activa **detección de presencia en el propio ESP32** (recomendado) |

Repite para cada sensor cambiando `--port`, `--node-id` y, si quieres, `--tdm-slot` en despliegues mesh.

---

### Paso 5 — Arrancar el servidor de sensado

**Con Docker (recomendado en Windows):**

```powershell
docker run --rm `
  -e CSI_SOURCE=esp32 `
  -p 3000:3000 `
  -p 3001:3001 `
  -p 5005:5005/udp `
  ruvnet/wifi-densepose:latest
```

**Desde código fuente (requiere Rust):**

```powershell
cd v2
cargo build --release
.\target\release\sensing-server.exe --source esp32 --udp-port 5005 --http-port 3000 --ws-port 3001
```

---

### Paso 6 — Verificar que funciona

```powershell
curl http://localhost:3000/health
curl http://localhost:3000/api/v1/nodes
curl http://localhost:3000/api/v1/sensing/latest
```

**Paneles web:**

| Vista | URL |
|-------|-----|
| Dashboard | http://localhost:3000/ui/index.html |
| Observatory | http://localhost:3000/ui/observatory.html |

En `sensing/latest` busca campos de **presencia**, **motion** y **occupancy**.

---

## Uso operativo para el equipo de limpieza

### Flujo diario sugerido

1. El recepcionista marca la habitación como “pendiente de limpieza”
2. El panel RuView muestra **LIBRE** u **OCUPADA** en tiempo real
3. Si está **LIBRE** → el camarista entra sin llamar
4. Si está **OCUPADA** → esperar o dejar aviso en recepción

### Integración futura (API)

Puedes conectar tu PMS (Property Management System) o una app propia:

```
GET http://<servidor>:3000/api/v1/sensing/latest   → estado actual
GET http://<servidor>:3000/api/v1/nodes            → lista de sensores por habitación
WebSocket :3001                                     → stream en tiempo real
```

### Calibración por habitación

La primera vez, deja la habitación **vacía 60 segundos** para que el sensor aprenda el “ruido ambiente”. Luego entra una persona y comprueba que el indicador cambia a ocupada.

Ajuste de sensibilidad (sin reflashear):

```powershell
python firmware/esp32-csi-node/provision.py --port COM7 `
  --ssid "WiFi-Hotel" --password "xxx" --target-ip 192.168.1.50 `
  --edge-tier 2 --pres-thresh 50
```

- `--pres-thresh` más **bajo** = más sensible (detecta antes, más falsos positivos)
- más **alto** = menos sensible

---

## Colocación física de sensores en la habitación

| Ubicación | Ventaja |
|-----------|---------|
| Techo, centro de la habitación | Cobertura general |
| Encima del cabecero / mueble TV | Buena línea de visión RF hacia la cama |
| Pasillo técnico / cuarto de instalaciones | Discreto, alimentación fácil |

**Evita:** dentro del baño con puerta metálica cerrada (atenua señal), junto al microondas, o pegado a otros APs WiFi.

---

## Plan de despliegue recomendado

| Fase | Acción | Duración |
|------|--------|----------|
| 1 | Demo Docker sin hardware | 1 día |
| 2 | Comprar 2× ESP32-S3 + probar 1 habitación piloto | 1–2 semanas |
| 3 | Calibrar y validar con personal de limpieza | 1 semana |
| 4 | Escalar a un piso completo | según tamaño |
| 5 | Integrar panel con recepción / app móvil | opcional |

---

## Privacidad y cumplimiento

- RuView **no graba video ni audio**
- Informa a huéspedes en la política de privacidad del hotel (sensor de ocupación por radio, no cámara)
- Mantén el servidor en red interna; no expongas el puerto 3000 a Internet sin autenticación
- El servidor advierte si escuchas en `0.0.0.0` sin proxy/TLS

---

## Solución de problemas frecuentes

| Problema | Solución |
|----------|----------|
| Windows no ve el ESP32 | Instalar driver CP210x; probar otro cable USB |
| No llegan datos al servidor | Verificar `--target-ip`, firewall UDP 5005, misma red WiFi |
| Siempre dice “ocupada” | Recalibrar con habitación vacía 60 s; subir `--pres-thresh` |
| Siempre dice “libre” | Bajar `--pres-thresh`; añadir segundo sensor |
| Puerto 5005 ocupado | Solo un proceso puede escuchar; cierra otros agregadores |
| Docker no arranca | Activar virtualización en BIOS; instalar WSL2 |

---

## Referencias del proyecto

| Documento | Contenido |
|-----------|-----------|
| [README.md](./README.md) | Visión general del proyecto |
| [docs/user-guide.md](./docs/user-guide.md) | Guía completa en inglés |
| [firmware/esp32-csi-node/README.md](./firmware/esp32-csi-node/README.md) | Firmware ESP32-S3 |
| [Releases ESP32](https://github.com/ruvnet/RuView/releases) | Binarios de firmware |
| [Modelo Hugging Face](https://huggingface.co/ruvnet/wifi-densepose-pretrained) | Modelo de presencia preentrenado |

---

## Resumen ejecutivo

| Pregunta | Respuesta |
|----------|-----------|
| ¿Puedo saber si hay alguien sin tocar la puerta? | **Sí**, con ESP32-S3 + RuView |
| ¿Cuánto cuesta probar? | **~25–30 €** (2 sensores) |
| ¿Cuánto por habitación en producción? | **~16–24 €** en hardware |
| ¿Necesito cámaras? | **No** |
| ¿Qué compro primero? | 2× **ESP32-S3 DevKitC-1 (8 MB)** + cable USB |
| ¿Cómo instalo? | Docker para servidor + `esptool` + `provision.py` para sensores |

---

*Guía generada para despliegue hotelero sobre RuView v1136 — Mayo 2026*
