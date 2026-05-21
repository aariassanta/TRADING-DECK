"""
app_modern.py - Alternate ttkbootstrap GUI for SPX 0DTE Trading Control Panel.

A very compact, professional light-themed widget for quick execution.
Uses the 'flatly' theme for a clean, institutional look.
"""

import asyncio
import sys

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
import concurrent.futures
from engine import IBKREngine

# Matplotlib and numpy are imported lazily (on first use)
# to significantly reduce application startup time.

# Compact Fonts
FONT_MAIN = ("Roboto", 11)
FONT_BOLD = ("Roboto", 11, "bold")
FONT_TITLE = ("Roboto", 14, "bold")
FONT_MACRO = ("Roboto", 11, "bold")

class SPXTradingPanel(ttk.Window):
    """Main application window using ttkbootstrap."""

    def __init__(self):
        # Professional light theme
        super().__init__(themename="flatly")

        self.title("Quantum Options - Mini Deck")
        self.geometry("640x410")
        self.resizable(False, False)

        # Configure root grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # State
        self.engine = None
        self.connected = False

        # ==================== CONTROLS (LEFT) ====================
        self.sidebar_frame = ttk.Frame(self)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.sidebar_frame.grid_rowconfigure(10, weight=1)

        # Title
        self.logo_label = ttk.Label(
            self.sidebar_frame, text="SPX 0DTE DECK",
            font=FONT_TITLE, bootstyle="primary"
        )
        self.logo_label.grid(row=0, column=0, pady=(5, 10))

        # Inputs (Tighter padding)
        self.create_sidebar_input("Quantity", "1", "qty", 2)
        self.create_target_selector(3)
        self.create_sidebar_input("Width", "10", "width", 4)
        self.create_sidebar_input("TP (%)", "50", "tp", 5)
        self.create_sidebar_input("SL (Multi)", "2.0", "sl", 6)
        self.create_sidebar_input("Port", "4002", "port", 7)

        # Toggle Switch
        self.var_transmit = tk.BooleanVar(value=False)
        self.chk_transmit = ttk.Checkbutton(
            self.sidebar_frame, text="Auto Transmit",
            variable=self.var_transmit, bootstyle="success-round-toggle"
        )
        self.chk_transmit.grid(row=8, column=0, pady=(10, 5), sticky="w", padx=5)

        # Connection Mod
        self.conn_frame = ttk.Frame(self.sidebar_frame)
        self.conn_frame.grid(row=11, column=0, pady=(15, 0), sticky="s")

        self.status_indicator = ttk.Label(self.conn_frame, text="● OFFLINE", font=FONT_BOLD, bootstyle="danger")
        self.status_indicator.pack(side="left", padx=5)

        self.btn_connect = ttk.Button(
            self.conn_frame, text="CONNECT", 
            bootstyle="primary", command=self.toggle_connection,
            width=12
        )
        self.btn_connect.pack(side="right")

        # ==================== MAIN AREA (RIGHT) ====================
        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        self.main_frame.grid_columnconfigure((0, 1), weight=1)
        self.main_frame.grid_rowconfigure((0, 1), weight=1)
        
        # Buttons (Compact Grid)
        self.btn_pcs = ttk.Button(
            self.main_frame, text="BULLISH PCS",
            bootstyle="success", command=lambda: self.execute_trade('PCS')
        )
        self.btn_pcs.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=(0, 5), ipady=15)

        self.btn_ccs = ttk.Button(
            self.main_frame, text="BEARISH CCS",
            bootstyle="danger", command=lambda: self.execute_trade('CCS')
        )
        self.btn_ccs.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=(0, 5), ipady=15)

        self.btn_ic = ttk.Button(
            self.main_frame, text="NEUTRAL IC",
            bootstyle="info", command=lambda: self.execute_trade('IC')
        )
        self.btn_ic.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=(5, 10), ipady=15)

        self.btn_panic = ttk.Button(
            self.main_frame, text="FLATTEN PORT",
            bootstyle="warning"
        )
        self.btn_panic.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=(5, 10), ipady=15)

        # Console Text Box
        self.log_box = ttk.Text(self.main_frame, height=4, font=("Courier", 11), 
                                bg="#f8f9fa", fg="#2c3e50", borderwidth=1, relief="solid")
        self.log_box.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(5, 0))
        self.main_frame.grid_rowconfigure(2, weight=1)

        self.btn_metrics = ttk.Button(
            self.main_frame, text="MARKET METRICS (0DTE LEVELS)",
            bootstyle="secondary", command=self.open_metrics_window
        )
        self.btn_metrics.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(5, 0), ipady=5)

        # Interval Map Button (Bottom Full Width)
        self.btn_interval = ttk.Button(
            self.main_frame, text="INTRADAY GEX INTERVAL MAP",
            bootstyle="info", command=self.open_interval_window
        )
        self.btn_interval.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(5, 0), ipady=5)

        self.log("System initialized. Light theme loaded.")

    # ------------------------------------------------------------------
    # UI Helpers
    # ------------------------------------------------------------------

    def create_sidebar_input(self, label_text, default_val, var_name, row):
        frame = ttk.Frame(self.sidebar_frame)
        frame.grid(row=row, column=0, pady=3, sticky="ew", padx=5)

        lbl = ttk.Label(frame, text=label_text, font=FONT_MAIN)
        lbl.pack(side="left")

        entry = ttk.Entry(frame, font=FONT_BOLD, width=5, justify="center")
        entry.insert(0, default_val)
        entry.pack(side="right")

        setattr(self, f"val_{var_name}", entry)

    def create_target_selector(self, row):
        frame = ttk.Frame(self.sidebar_frame)
        frame.grid(row=row, column=0, pady=3, sticky="ew", padx=5)

        self.var_target_mode = tk.StringVar(value="Delta")
        target_cb = ttk.Combobox(
            frame, 
            textvariable=self.var_target_mode, 
            values=["Delta", "R:R"], 
            state="readonly", 
            width=7, 
            font=FONT_MAIN
        )
        target_cb.pack(side="left")
        
        self.val_target = ttk.Entry(frame, font=FONT_BOLD, width=5, justify="center")
        self.val_target.insert(0, "50")  # Default Delta per user request
        self.val_target.pack(side="right")
        
        target_cb.bind("<<ComboboxSelected>>", self.on_target_mode_change)

    def on_target_mode_change(self, event):
        mode = self.var_target_mode.get()
        self.val_target.delete(0, tk.END)
        if mode == "Delta":
            self.val_target.insert(0, "50")
        else:
            self.val_target.insert(0, "1.75")

    def log(self, msg):
        self.log_box.insert(tk.END, "> " + msg + "\n")
        self.log_box.see(tk.END)

    # ------------------------------------------------------------------
    # Metrics Window Integration
    # ------------------------------------------------------------------
    
    def open_metrics_window(self):
        if not self.connected or not self.engine:
            self.log("ERROR: Must be CONNECTED to view live market metrics.")
            return
            
        MetricsWindow(self, self.engine, self.ib_loop)

    def open_interval_window(self):
        self.interval_window = IntervalMapWindow(self)

    # ------------------------------------------------------------------
    # Connection Logic
    # ------------------------------------------------------------------

    def toggle_connection(self):
        # We also check the real socket state just in case it dropped silently
        real_connected = self.connected and (self.engine and self.engine.ib.isConnected())
        
        if self.connected or not real_connected and self.btn_connect.cget("text") == "DISCONNECT":
            if self.engine:
                try:
                    self.engine.disconnect()
                except Exception:
                    pass
            if hasattr(self, 'ib_loop') and self.ib_loop.is_running():
                try:
                    self.ib_loop.call_soon_threadsafe(self.ib_loop.stop)
                except Exception:
                    pass
                
            self.status_indicator.configure(text="● OFFLINE", bootstyle="danger")
            self.btn_connect.configure(text="CONNECT", bootstyle="primary")
            self.log("Disconnected from Interactive Brokers.")
            self.connected = False
        else:
            self.btn_connect.configure(text="WAIT...", bootstyle="warning")
            threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        try:
            port = int(self.val_port.get())
        except ValueError:
            self.log("ERROR: Port must be a number.")
            self.btn_connect.configure(text="CONNECT", bootstyle="primary")
            return

        self.ib_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.ib_loop)

        self.engine = IBKREngine(port=port)
        self.log(f"Connecting port {port}...")

        success, err = self.ib_loop.run_until_complete(self.engine.connect_async())

        if success:
            self.connected = True
            
            def on_ibkr_error(reqId, errorCode, errorString, contract):
                # Ignore 200 (No definition found for weekends), 2104, 2106, 2158 (Farm conn)
                if errorCode not in [200, 2104, 2106, 2158]:
                    self.log(f"🛑 IBKR ERROR {errorCode}: {errorString}")
            self.engine.ib.errorEvent += on_ibkr_error

            self.status_indicator.configure(text="● ONLINE", bootstyle="success")
            self.btn_connect.configure(text="DISCONNECT", bootstyle="dark")
            self.log(f"Connected to IBKR.")
            self.ib_loop.run_forever()
        else:
            self.engine = None
            self.btn_connect.configure(text="CONNECT", bootstyle="primary")
            self.log(f"FAILED: {err}")

    # ------------------------------------------------------------------
    # Trade Execution
    # ------------------------------------------------------------------

    def execute_trade(self, trade_type: str):
        try:
            qty = int(self.val_qty.get())
            target_mode = self.var_target_mode.get()
            target_value = float(self.val_target.get())
            width = int(self.val_width.get())
            tp_pct = float(self.val_tp.get())
            sl_ratio = float(self.val_sl.get())
            transmit = self.var_transmit.get()
        except ValueError:
            self.log("ERROR: Invalid parameter format.")
            return

        if sl_ratio < 1.2:
            self.log("ERROR: SL Multiplier cannot be less than 1.2x.")
            return

        if not self.connected or not self.engine:
            self.log("ERROR: Not connected.")
            return
            
        # Catch silent TCP socket drops (e.g. if the computer went to sleep)
        if hasattr(self.engine, 'ib') and not self.engine.ib.isConnected():
            self.log("ERROR: Connection to IBKR was lost (socket dropped).")
            self.log("Action required: Please click DISCONNECT and then CONNECT again.")
            self.status_indicator.configure(text="● OFFLINE", bootstyle="danger")
            self.btn_connect.configure(text="CONNECT", bootstyle="primary")
            self.connected = False
            return

        if not hasattr(self, 'ib_loop') or not self.ib_loop.is_running():
            self.log("ERROR: IB loop dead. Reconnect.")
            return

        self.log(f"[{trade_type}] Launching... {target_mode}:{target_value} / {width}pts")

        def dispatch():
            future = asyncio.run_coroutine_threadsafe(
                self.engine.execute_spread(
                    trade_type, qty, target_mode, target_value, width, tp_pct, sl_ratio, transmit
                ),
                self.ib_loop
            )
            try:
                future.result(timeout=60)
                status = "LIVE" if transmit else "PENDING"
                self.log(f"[{trade_type}] ✅ Order -> {status}")
            except Exception as e:
                import traceback
                self.log(f"[{trade_type}] ERROR: {repr(e)}\n{traceback.format_exc()}")

        threading.Thread(target=dispatch, daemon=True).start()


class GexHeatMap(tk.Frame):
    """
    Scrollable heat map table: rows = strikes (desc), columns = expiry dates.
    Green = positive GEX (dealer long), Red = negative GEX (dealer short).
    Color intensity scales with magnitude relative to the max absolute GEX.
    """

    # Layout constants
    ROW_HEIGHT = 16       # px per strike row
    COL_WIDTH_STRIKE = 65 # px for the strike label column
    COL_WIDTH_DATA = 80   # px per expiry data column
    HEADER_HEIGHT = 22    # px for the column headers

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#1a1a2e", **kwargs)
        self._build_canvas()

    def _build_canvas(self):
        """Build the scrollable canvas and attach the scrollbar."""
        self.canvas = tk.Canvas(self, bg="#1a1a2e", highlightthickness=0)
        self.vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # Mouse-wheel scroll support
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    @staticmethod
    def _fmt_gex(val: float) -> str:
        """Format GEX value: 1.25 B / 345 M / -2.10 B."""
        if abs(val) >= 1000:
            return f"{val/1000:.2f} B"
        return f"{val:.2f} M"

    @staticmethod
    def _gex_color(val: float, max_abs: float) -> str:
        """
        Map a GEX value to an HTML hex color.
        Positive → green shades; Negative → red shades; Near 0 → dark gray.
        """
        if max_abs == 0:
            return "#2a2a3e"
        intensity = min(abs(val) / max_abs, 1.0)  # 0.0 to 1.0
        if val > 0:
            # Dark green (#0d2b0d) → vivid green (#00b300)
            r = int(0 + intensity * 0)
            g = int(43 + intensity * (179 - 43))
            b = int(13 + intensity * 13)
        elif val < 0:
            # Dark red (#2b0d0d) → vivid red (#cc0000)
            r = int(43 + intensity * (204 - 43))
            g = int(13 + intensity * 0)
            b = int(13 + intensity * 0)
        else:
            return "#2a2a3e"
        return f"#{r:02x}{g:02x}{b:02x}"

    def render(self, gex_by_expiry: dict, expiries: list, spot: float):
        """Draw the full heat map on the canvas."""
        self.canvas.delete("all")

        if not gex_by_expiry or not expiries:
            self.canvas.create_text(
                200, 80, text="No GEX data available.", fill="#aaaaaa",
                font=("Courier", 12)
            )
            return

        # Determine strike range: ±80 pts around spot (~16 strikes above/below)
        # Matches the engine's 60-contract per expiry batch (+/- 15 strikes)
        step = 5
        strikes = sorted(
            set(s for exp_data in gex_by_expiry.values() for s in exp_data.keys()
                if abs(s - spot) <= 80),
            reverse=True  # Highest strike on top
        )
        if not strikes:
            return

        # Find max absolute GEX for colour scaling
        all_vals = [v for exp_data in gex_by_expiry.values() for v in exp_data.values()]
        max_abs = max((abs(v) for v in all_vals), default=1.0)

        # Column layout
        cols = expiries  # one column per expiry date
        total_width = self.COL_WIDTH_STRIKE + self.COL_WIDTH_DATA * len(cols)
        total_height = self.HEADER_HEIGHT + self.ROW_HEIGHT * len(strikes)
        
        # Horizontal centering logic
        canvas_w = self.canvas.winfo_width()
        if canvas_w < 10:  # If not yet rendered, use a sensible default
            canvas_w = 780
        x_offset = max(0, (canvas_w - total_width) // 2)
        
        self.canvas.configure(scrollregion=(0, 0, max(total_width + x_offset, canvas_w), total_height))

        font_hdr = ("Courier", 9, "bold")
        font_cell = ("Courier", 9)

        # -- Header row --
        self.canvas.create_rectangle(
            x_offset, 0, x_offset + self.COL_WIDTH_STRIKE, self.HEADER_HEIGHT, fill="#0d0d1a", outline=""
        )
        self.canvas.create_text(
            x_offset + self.COL_WIDTH_STRIKE // 2, self.HEADER_HEIGHT // 2,
            text="Strike", fill="#cccccc", font=font_hdr
        )
        for ci, exp in enumerate(cols):
            x0 = x_offset + self.COL_WIDTH_STRIKE + ci * self.COL_WIDTH_DATA
            x1 = x0 + self.COL_WIDTH_DATA
            # Format: "Mar 18" style
            try:
                import datetime
                d = datetime.datetime.strptime(exp[:8], "%Y%m%d")
                label = d.strftime("%b %d (%a)")
            except Exception:
                label = exp[:8]
            self.canvas.create_rectangle(x0, 0, x1, self.HEADER_HEIGHT, fill="#0d0d1a", outline="#333355")
            self.canvas.create_text(
                (x0 + x1) // 2, self.HEADER_HEIGHT // 2,
                text=label, fill="#99bbff", font=font_hdr
            )

        # -- Data rows --
        for ri, strike in enumerate(strikes):
            y0 = self.HEADER_HEIGHT + ri * self.ROW_HEIGHT
            y1 = y0 + self.ROW_HEIGHT

            # Is this the spot price row?
            is_spot_row = abs(strike - spot) < step / 2.0
            strike_bg = "#f0c040" if is_spot_row else "#1a1a2e"
            strike_fg = "#000000" if is_spot_row else "#dddddd"

            # Strike label cell
            self.canvas.create_rectangle(
                x_offset, y0, x_offset + self.COL_WIDTH_STRIKE, y1, fill=strike_bg, outline="#333355"
            )
            self.canvas.create_text(
                x_offset + self.COL_WIDTH_STRIKE // 2 - 2, (y0 + y1) // 2,
                text=f"${strike:,.0f}", fill=strike_fg, font=font_cell, anchor="center"
            )

            # Data cells
            for ci, exp in enumerate(cols):
                x0 = x_offset + self.COL_WIDTH_STRIKE + ci * self.COL_WIDTH_DATA
                x1 = x0 + self.COL_WIDTH_DATA
                val = gex_by_expiry.get(exp, {}).get(strike, None)

                if val is None:
                    cell_bg = "#1a1a2e"
                    label = ""
                    fg = "#555577"
                else:
                    cell_bg = self._gex_color(val, max_abs)
                    label = self._fmt_gex(val)
                    fg = "#ffffff" if abs(val) / max_abs > 0.15 else "#aaaaaa"

                self.canvas.create_rectangle(x0, y0, x1, y1, fill=cell_bg, outline="#222244")
                if label:
                    self.canvas.create_text(
                        (x0 + x1) // 2, (y0 + y1) // 2,
                        text=label, fill=fg, font=font_cell, anchor="center"
                    )

        # Scroll to center on the spot price row
        spot_ri = next((i for i, s in enumerate(strikes) if abs(s - spot) < step / 2.0), 0)
        if total_height > 0:
            target_frac = max(0.0, (spot_ri - 5) / len(strikes))
            self.canvas.yview_moveto(target_frac)


class MetricsWindow(ttk.Toplevel):
    """Secondary window to display 0DTE Options Market Metrics."""
    
    def __init__(self, parent, engine, ib_loop):
        super().__init__(parent)
        self.title("Market Metrics")
        self.geometry("780x660")
        self.resizable(True, True)
        
        self.parent_app = parent
        self.engine = engine
        self.ib_loop = getattr(parent, 'ib_loop', None)
        self.parent_log = getattr(parent, 'log_message', print)       
        
        self.var_auto_refresh = tk.BooleanVar(value=False)
        
        # UI Setup
        self.setup_ui()
        
        # Auto-fetch on open
        self.refresh_metrics()
        
        # Start auto-refresh timer loop
        self._check_auto_refresh()

    def setup_ui(self):
        # Master layout using pack for the header and panedwindow for the content
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # --- HEADER (Top Row) ---
        header_frame = ttk.Frame(self, padding=(10, 2), bootstyle="dark")
        header_frame.grid(row=0, column=0, sticky="ew")
        
        self.lbl_spot = ttk.Label(header_frame, text="SPX SPOT: Loading...", font=("Roboto", 12, "bold"), bootstyle="inverse-dark")
        self.lbl_spot.pack(side="left", padx=5)
        
        self.btn_refresh = ttk.Button(header_frame, text="↻ REFRESH", bootstyle="info-outline", command=self.refresh_metrics)
        self.btn_refresh.pack(side="right", padx=5)
        
        self.sw_auto = ttk.Checkbutton(
            header_frame, 
            text="AUTO", 
            variable=self.var_auto_refresh, 
            bootstyle="success-round-toggle",
            command=self._on_toggle_auto
        )
        self.sw_auto.pack(side="right", padx=10)
        
        self.lbl_updated = ttk.Label(header_frame, text="Updated: --:--:--", font=("Roboto", 10, "italic"), bootstyle="inverse-dark")
        self.lbl_updated.pack(side="right", padx=15)
        
        # --- PANED WINDOW (Main Area) ---
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")
        
        # --- LEFT SIDEBAR ---
        sidebar = ttk.Frame(paned, padding=8, width=280)
        paned.add(sidebar, weight=0)
        sidebar.pack_propagate(False) # Strict width
        
        card_style = "secondary"
        
        # 1. Key Levels
        lf_key = ttk.Labelframe(sidebar, text="💰 Key Walls", padding=5, bootstyle=card_style)
        lf_key.pack(fill="x", pady=(0, 5))
        
        self.var_call_wall = tk.StringVar(value="--")
        self.var_put_wall = tk.StringVar(value="--")
        self.var_gamma_flip = tk.StringVar(value="--")
        
        self._add_metric_row(lf_key, "Call Wall:", self.var_call_wall, "danger", 0)
        self._add_metric_row(lf_key, "G-Flip:", self.var_gamma_flip, "warning", 1)
        self._add_metric_row(lf_key, "Put Wall:", self.var_put_wall, "success", 2)
        
        # 2. Sigma Levels
        lf_sigma = ttk.Labelframe(sidebar, text="📊 σ Levels", padding=5, bootstyle=card_style)
        lf_sigma.pack(fill="x", pady=5)
        
        self.var_sigmas = {k: tk.StringVar(value="--") for k in ["+3","+2","+1","-1","-2","-3"]}
        sig_inner = ttk.Frame(lf_sigma)
        sig_inner.pack(fill="both", expand=True)
        
        def add_sig_v(p, l, v, b, r):
             ttk.Label(p, text=l, font=("Roboto", 9)).grid(row=r, column=0, sticky="w", pady=0)
             ttk.Label(p, textvariable=v, font=("Roboto", 9, "bold"), bootstyle=b).grid(row=r, column=1, sticky="e")
             p.grid_columnconfigure(1, weight=1)

        add_sig_v(sig_inner, "+3σ Up", self.var_sigmas["+3"], "danger", 0)
        add_sig_v(sig_inner, "+2σ Up", self.var_sigmas["+2"], "warning", 1)
        add_sig_v(sig_inner, "+1σ Up", self.var_sigmas["+1"], "secondary", 2)
        ttk.Separator(sig_inner, orient="horizontal").grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
        add_sig_v(sig_inner, "-1σ Dn", self.var_sigmas["-1"], "secondary", 4)
        add_sig_v(sig_inner, "-2σ Dn", self.var_sigmas["-2"], "info", 5)
        add_sig_v(sig_inner, "-3σ Dn", self.var_sigmas["-3"], "success", 6)
        
        # 3. Dark Gamma
        lf_dark = ttk.Labelframe(sidebar, text="🕵️ Dark G", padding=5, bootstyle=card_style)
        lf_dark.pack(fill="both", expand=True, pady=5)
        self.dark_gamma_text = ttk.Text(lf_dark, font=("Courier", 10), bg="#f8f9fa", state="disabled", height=8)
        self.dark_gamma_text.pack(fill="both", expand=True)

        # --- RIGHT AREA (Heat Map) ---
        hm_container = ttk.Frame(paned, padding=(2, 0))
        paned.add(hm_container, weight=1)

        self.heat_map = GexHeatMap(hm_container)
        self.heat_map.pack(fill="both", expand=True)

    def _add_metric_row(self, parent, label, var, bootstyle, row):
        ttk.Label(parent, text=label, font=("Roboto", 10)).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(parent, textvariable=var, font=("Roboto", 11, "bold"), bootstyle=bootstyle).grid(row=row, column=1, sticky="e", pady=2)
        parent.grid_columnconfigure(1, weight=1)

    def _on_toggle_auto(self):
        """Immediately refresh if AUTO is turned ON and not currently loading."""
        if self.var_auto_refresh.get():
            self.parent_log("[Metrics] Auto-refresh enabled. Initializing...")
            if str(self.btn_refresh.cget("state")) == "normal":
                self.refresh_metrics()

    def _check_auto_refresh(self):
        """Timer loop that triggers refresh if AUTO is enabled."""
        if self.var_auto_refresh.get() and str(self.btn_refresh.cget("state")) == "normal":
            self.parent_log("[Metrics] Auto-refresh: 5-minute tick triggered.")
            self.refresh_metrics()
        
        # Check again in 5 minutes (300,000 ms)
        self.after(300000, self._check_auto_refresh)

    def refresh_metrics(self):
        self.btn_refresh.configure(state="disabled", text="↻ LOADING...")
        self.lbl_spot.configure(text="SPX SPOT: Calculating...")
        self.parent_log("[Metrics] Fetching 0DTE chain data. This takes a few seconds...")
        
        # Run the async fetcher from the background IB thread safely
        def fetch_task():
            future = asyncio.run_coroutine_threadsafe(
                self.engine.fetch_market_metrics(), 
                self.ib_loop
            )
            try:
                result = future.result(timeout=120.0)
                # GUI updates must be scheduled back to the main thread
                self.after(0, lambda: self._update_ui_data(result))
            except concurrent.futures.TimeoutError:
                self.parent_log("ERROR Fetching Metrics: Time out (took longer than 120s)")
                self.after(0, self._handle_fetch_error)
            except Exception as e:
                import traceback
                self.parent_log(f"ERROR Fetching Metrics: {str(e) or type(e).__name__}")
                self.after(0, self._handle_fetch_error)
                
        threading.Thread(target=fetch_task, daemon=True).start()
        
    def _update_ui_data(self, data):
        self.btn_refresh.configure(state="normal", text="↻ REFRESH")
        
        import datetime
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        self.lbl_updated.configure(text=f"Updated at {now_str}")
        
        if "error" in data:
            self.lbl_spot.configure(text="STATUS: " + data["error"])
            return
            
        # Update Spot Price
        spot = data.get("spot", 0)
        self.lbl_spot.configure(text=f"SPX SPOT: {spot:,.2f}")
        
        # Update Walls
        self.var_call_wall.set(str(data.get("call_wall", "--")))
        self.var_put_wall.set(str(data.get("put_wall", "--")))
        self.var_gamma_flip.set(str(data.get("gamma_flip", "--")))
        
        # Update Sigmas
        sigmas = data.get("sigmas", {})
        for key in self.var_sigmas.keys():
            val = sigmas.get(key, "--")
            if val != "--":
                self.var_sigmas[key].set(f"{val:,.2f}")
                
        # Update Dark Gamma
        dg_list = data.get("dark_gamma", [])
        self.dark_gamma_text.configure(state="normal")
        self.dark_gamma_text.delete("1.0", tk.END)
        
        if not dg_list:
            self.dark_gamma_text.insert(tk.END, "No extreme prints detected.\n")
        else:
            for item in dg_list:
                strike = item['strike']
                typ = item['type']
                vol = item['volume']
                oi = item['oi']
                ratio = item['ratio']
                self.dark_gamma_text.insert(tk.END, f"{strike} {typ} | Vol:{vol} OI:{oi} (x{ratio})\n")
                
        self.dark_gamma_text.configure(state="disabled")
        
        # Update GEX Heat Map
        gex_by_expiry = data.get("gex_by_expiry", {})
        expiries = data.get("expiries", [])
        self.heat_map.render(gex_by_expiry, expiries, spot)
        
        self.parent_log("[Metrics] Display updated successfully.")
        
        # Auto-update the Interval Map if it's currently open
        if hasattr(self, 'parent_app') and hasattr(self.parent_app, 'interval_window') and self.parent_app.interval_window and self.parent_app.interval_window.winfo_exists():
            try:
                self.parent_app.interval_window.load_data()
            except Exception as e:
                self.parent_log(f"Map Sync Error: {e}")




    def _handle_fetch_error(self):
        self.btn_refresh.configure(state="normal", text="↻ REFRESH")
        self.lbl_spot.configure(text="ERROR: TIMEOUT / FAILURE")


class IntervalMapWindow(ttk.Toplevel):
    """
    Renders the Intraday GEX Interval Map: 
    - X-Axis: Time (HH:MM)
    - Y-Axis: Strike Price
    - Scatter Bubbles: Volume-scaled, GEX-colored
    - Line Plot: SPX Spot Price evolution
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Intraday GEX Interval Map - SPX 0DTE")
        self.geometry("1100x750")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.main_frame = ttk.Frame(self, padding=10)
        self.main_frame.pack(fill="both", expand=True)

        header = ttk.Frame(self.main_frame)
        header.pack(fill="x", pady=(0, 10))
        
        ttk.Label(header, text="🔥 INTRADAY GEX BUBBLE MAP", font=("Roboto", 14, "bold")).pack(side="left")
        ttk.Button(header, text="↻ REFRESH", bootstyle="primary", command=self.load_data).pack(side="right")

        import matplotlib
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        # GridSpec for splitting main chart (left) and volume/GEX profile (right)
        self.fig = Figure(figsize=(12, 7), dpi=100)
        self.fig.patch.set_facecolor('#1a1a2e')

        # Create GridSpec allowing a 4:1 ratio for Main vs Profile
        gs = self.fig.add_gridspec(1, 4, wspace=0.05)
        self.ax = self.fig.add_subplot(gs[0, :3])
        self.ax_prof = self.fig.add_subplot(gs[0, 3], sharey=self.ax)
        
        self.ax.set_facecolor('#1a1a2e')
        self.ax_prof.set_facecolor('#1a1a2e')
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.main_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        self.after(100, self.load_data)

    def on_close(self):
        self.destroy()

    def load_data(self):
        import os, glob, csv, datetime
        import matplotlib.dates as mdates
        import pandas as pd
        import numpy as np
        
        history_dir = os.path.join(os.path.dirname(__file__), 'history')
        if not os.path.exists(history_dir):
            return

        # Find today's file or the most recent one
        files = glob.glob(os.path.join(history_dir, "gex_intraday_*.csv"))
        if not files:
            return
            
        latest_file = max(files, key=os.path.getctime)
        
        try:
            df = pd.read_csv(latest_file)
            if df.empty:
                return
                
            # Parse timestamps
            # df['Timestamp'] is HH:MM:SS
            # We will convert it to a datetime object for matplotlib plotting
            today_str = datetime.date.today().strftime('%Y-%m-%d')
            df['Datetime'] = pd.to_datetime(today_str + ' ' + df['Timestamp'])
            
            # Normalize strike values to the nearest multiple of 5 and aggregate duplicate strike rows
            df['Strike'] = (df['Strike'] / 5.0).round() * 5
            df['Strike'] = df['Strike'].astype(int)
            df = df.groupby(['Datetime', 'Strike']).agg({
                'NetGEX': 'sum',
                'Volume': 'sum',
                'Spot': 'last'
            }).reset_index()
            
            self.ax.clear()
            self.ax_prof.clear()

            self.ax.set_facecolor('#0f172a')
            self.ax_prof.set_facecolor('#0f172a')

            # 1. BUBBLES
            # Size proportional to Volume (or NetGEX magnitude if Volume is 0 but GEX exists)
            # In Option chains, volume is cumulative intraday. We want the INTERVAL volume...
            # BUT the user screenshot literally just maps the Raw Values at that timestamp.
            # We will use Total Volume to scale, or use absolute GEX to scale sizes.
            
            # To emulate the user's reference exactly:
            # Color: Positive GEX = Green, Negative GEX = Red
            colors = np.where(df['NetGEX'] > 0, '#00ff00', '#ff0044')
            
            # Bubble Size represents the MAGNITUDE of the Gamma Wall (Absolute NetGEX)
            # We use Min-Max scaling to make the biggest walls pop visually.
            gex_mag = df['NetGEX'].abs()
            g_min = gex_mag.min()
            g_max = gex_mag.max()
            if g_max > g_min:
                sizes = 10 + ((gex_mag - g_min) / (g_max - g_min)) * 1200
            else:
                sizes = 100
            
            # Scatter Plot
            self.ax.scatter(df['Datetime'], df['Strike'], s=sizes, c=colors, alpha=0.6, edgecolors='none')

            # 2. SPOT PRICE LINE
            # Spot price is the same for all rows in a given timestamp, so we group by Datetime
            spot_df = df.groupby('Datetime')['Spot'].last().reset_index()
            self.ax.plot(spot_df['Datetime'], spot_df['Spot'], color='#33ccff', linewidth=2, label='SPX Spot')
            self.ax.scatter(spot_df['Datetime'], spot_df['Spot'], color='#33ccff', s=15, zorder=5) # Dots on the line

            # X-Axis Time Formatting
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            self.ax.tick_params(axis='x', colors='#a0a0b0')
            self.ax.tick_params(axis='y', colors='#a0a0b0')
            self.ax.grid(True, linestyle='--', color='#2a2a4a', alpha=0.5)

            # Limit Y Axis around spotting price (aligned to multiples of 5)
            latest_spot = spot_df['Spot'].iloc[-1]
            y_min = int(round((latest_spot - 50) / 5) * 5)
            y_max = int(round((latest_spot + 50) / 5) * 5)
            self.ax.set_ylim(y_min, y_max)
            
            # Title
            self.ax.set_title(f"0DTE Net GEX Interval Map", color='white', pad=10)

            # 3. RIGHT PROFILE (LATEST Cumulative Volume / GEX)
            # The right pane should show the generic horizontal bar chart of the LATEST timestamp
            latest_time = spot_df['Datetime'].iloc[-1]
            latest_df = df[df['Datetime'] == latest_time]
            
            # Since user wants GEX Profile here
            pos_gex = latest_df[latest_df['NetGEX'] > 0]
            neg_gex = latest_df[latest_df['NetGEX'] < 0]
            
            self.ax_prof.barh(pos_gex['Strike'], pos_gex['NetGEX'], height=4.0, color='#00ff00', alpha=0.7)
            self.ax_prof.barh(neg_gex['Strike'], neg_gex['NetGEX'], height=4.0, color='#ff0044', alpha=0.7)
            
            self.ax_prof.axvline(0, color='white', linewidth=1, alpha=0.3)
            self.ax_prof.tick_params(axis='x', colors='#a0a0b0', labelsize=8)
            self.ax_prof.tick_params(axis='y', left=False, labelleft=False)
            
            # Suppress matplotlib tightly_layout Warning for gridspecs
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                self.fig.tight_layout()
            
            self.canvas.draw()
            
        except Exception as e:
            print(f"Error loading map data: {e}")

if __name__ == "__main__":
    app = SPXTradingPanel()
    app.mainloop()
