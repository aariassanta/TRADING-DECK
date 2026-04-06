# TRADING DECK - 0DTE GEX Strategy

El **Trading Deck** es una plataforma operativa de opciones avanzada para IBKR enfocada en estrategias institucionales de *Gamma Exposure (GEX)*, *Open Interest (OI)* y volumen intradiario para operaciones de SPX (0DTE). 

En lugar de ofrecer solo gráficas e indicadores tradicionales, esta herramienta analiza las posiciones de los *dealers* y la estructura estructural de opciones para anticipar si el precio rebotará en un nivel o acelerará al cruzarlo.

---

## 🧭 Conceptos Clave de la Estrategia

El panel clasifica automáticamente el mercado a nivel intradía utilizando las siguientes métricas:

### 1. Market Regime (Régimen de Mercado)
Dependiendo de dónde esté el Spot relativo al *Gamma Flip* (el nivel donde el GEX total del mercado cruza el nivel cero), el mercado operará en uno de dos regímenes:

- 🟢 **LONG GAMMA (+)**: El mercado estabiliza. Los dealers están comprados en Gamma y necesitan vender en las subidas y comprar en las bajadas. Las caídas son absorbidas. **[Operativa Sugerida: FADE / Mean-Reversion]**
- 🔴 **SHORT GAMMA (-)**: El mercado acelera. Los dealers están cortos en Gamma y necesitan seguir la tendencia (vender si cae, comprar si sube). Aumenta significativamente la volatilidad (Vol Spike). **[Operativa Sugerida: BREAKOUT / Momentum]**

### 2. GEX Zones (Zonas de Liquidez)
En el HeatMap (y en el panel de Señales), los niveles de precios de SPX aparecerán con banderas direccionales (🟢/🔴):
- **🟢 FADE (GEX +):** El strike actúa como un amortiguador o resistencia institucional. Son niveles perfectos para buscar agotamientos o fijar el `Stop Loss` detrás de ellos.
- **🔴 BREAKOUT (GEX -):** Zonas de aceleración. Si el SPX cruza estos strikes y los rompe, el movimiento hacia el siguiente escalón se hará de golpe ("efecto vacío"). No operar Credit Spreads direccionales intentando parar la caída contra estos niveles.

### 3. Confluencias (⚡) y Dark Gamma
Solo aplicable al vencimiento 0DTE. Una confluencia temporal ocurre cuando en el día actual el **Volumen de un Strike es al menos 50% mayor de su Open Interest existente**. 
- Aparece marcado con un ⚡ en la columna del HeatMap. 
- Significa una agresiva toma de postura intradiaria que puede crear trampas bajistas/alcistas. El mercado tiende a reaccionar más rápido a estos niveles.

### 4. Anchoring (Walls)
- **Call Wall / Put Wall:** Los dominios máximos del OI de Calls y Puts. El "Call Wall" es el principal techo estimado y el "Put Wall" es el suelo. Si no hay catalizadores macro, el Spot acostumbra a fluctuar cerrando entre estos dos bloques (*Pinning Effect*).

---

## 🛠 Cómo Operar en el Trading Deck

### Tipos de Operaciones (Execution Engine)
Desde el panel central inferior, puedes seleccionar el tipo de Trade (Credit Spreads) y su modo de apunte (Target By):

1. **Delta (Δ):** Método tradicional. Vendes el spread calculando el nivel probabilístico por griegas. (P.e. Vender la delta 0.20 o 20%).
2. **R:R (Risk:Reward):** Busca el nivel de máxima ganancia aceptando un ratio específico, calculando el fill algorítmicamente desde el motor. P.e. targetear un spread que cobre 1.00$ de crédito con 5.00$ de ancho (R:R de $4 arriesgados por cada $1 ganado).
3. 🎯 **GEX Wall (Modo Recomendado):** Desactiva las deltas. Utiliza la matemática del mercado institucional anclando mecánicamente la "Pata Corta" (la que da ganancia) directamente bajo el *Call Wall* o sobre el *Put Wall*.
    - Si el mercado está en `LONG GAMMA` 🟢, ejecutar la opción contraria contra un *Wall* provee una extrema ventaja probabilística, porque el hedge rema matemáticamente a nuestro favor.

### Click-To-Prefill (Rapidez Operativa)
- Cuando el monitor detecte cruces críticos en segundo plano, publicará el Setup Actuál (Ej: `📍 CCS fade ≤ 6650 | TP → 6600`) debajo del Regime Panel.
- **Haz CLICK directo** en el texto del setup de la alerta.
- El panel *Execution Engine* se **autocompletará** copiando esas direcciones y configurando mecánicamente el modo y ancho que se recomienda en ese instante, listo para enviar la orden en el botón `Launch`.

### Persistencia y Seguridad 
Tu configuración del *Execution Engine* (Anchuras, Lotes, Stop Loss 2.5x, Take Profit %, etc) se **guarda automáticamente**. Al reiniciar o refrescar, todos los parámetros continuarán como se deseaban. Siempre y cuando la casilla de segurirdad `STAGE (Pendiente)` figure como elegida, el motor jamás lanzará órdenes a mercado — todas las órdenes quedarán posadas en espera de confirmación manual en su TWS para ser revisadas con tranquilidad.

---

## 🖥 Arranque de los Servidores del Sistema

El proyecto necesita dos terminales separadas, ya que el motor funciona como una API para evitar que la UI pesada del navegador sature la red de API de TWS.

👉 **Paso 1: Abrir Terminal 1 (Raíz del proyecto)**
*Asegúrate de que TWS o IB Gateway esté abierto, conectado y haciendo login.*
```bash
# Arrancar el procesador y el canal de datos de opciones
# (usa Python del entorno virtual "venv_new")
venv_new/bin/python3 server.py
```

👉 **Paso 2: Abrir Terminal 2 (Carpeta Frontend)**
```bash
# Arrancar la vista de React del Dashboard
cd frontend
npm run dev
```

Ya podrás abrir **http://localhost:5175** u operar directamente visualizando The Bubble Map en Vivo.
