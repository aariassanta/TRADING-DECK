"""
app.py - The SPX 0DTE Trading Control Panel GUI.

Uses CustomTkinter for a modern dark dashboard, ib_insync for IBKR routing.
All I/O operations (connect, trade) are dispatched in daemon threads so the
GUI never freezes.
"""

import asyncio
import sys

# ib_insync's dependency (eventkit) requires an asyncio event loop to exist at import time.
# Python 3.10+ no longer auto-creates one, so we create it explicitly here before any imports.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import tkinter as tk
import customtkinter as ctk
import threading
from engine import IBKREngine


# Premium Dark Theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Design Tokens
COLOR_BG = "#121212"
COLOR_SIDEBAR = "#1E1E1E"
COLOR_PANEL = "#252525"
COLOR_TEXT_PRIMARY = "#FFFFFF"
COLOR_TEXT_SEC = "#AAAAAA"
FONT_MAIN = ("Roboto", 14)
FONT_BOLD = ("Roboto", 14, "bold")
FONT_TITLE = ("Roboto", 24, "bold")
FONT_MACRO = ("Roboto", 18, "bold")


class SPXTradingPanel(ctk.CTk):
    """Main application window for the SPX 0DTE control panel."""

    def __init__(self):
        super().__init__()

        self.title("Quantum Options - 0DTE SPX Protocol")
        self.geometry("900x700")
        self.resizable(False, False)

        # Configure grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.configure(fg_color=COLOR_BG)

        # State
        self.engine = None
        self.connected = False

        # ==================== SIDEBAR (LEFT) ====================
        self.sidebar_frame = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        # Row 12 is an empty spacer that absorbs all extra space, keeping all content fixed at the top
        self.sidebar_frame.grid_rowconfigure(12, weight=1)

        # Title
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="QUANTUM\nOPTIONS",
                                        font=FONT_TITLE, text_color="#3498db")
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 10))

        self.subtitle = ctk.CTkLabel(self.sidebar_frame, text="P. Kan Protocol",
                                      font=FONT_MAIN, text_color=COLOR_TEXT_SEC)
        self.subtitle.grid(row=1, column=0, padx=20, pady=(0, 30))

        # Strategy parameter inputs
        self.create_sidebar_input("Quantity (Lots)", "1", "qty", 2)
        self.create_sidebar_input("Target Delta (Δ)", "20", "delta", 3)
        self.create_sidebar_input("Spread Width (Pts)", "15", "width", 4)
        self.create_sidebar_input("Take Profit (%)", "50", "tp", 5)
        self.create_sidebar_input("Stop Loss (xCredit)", "2.5", "sl", 6)

        # Port separator
        sep = ctk.CTkFrame(self.sidebar_frame, height=1, fg_color="#34495e")
        sep.grid(row=7, column=0, padx=20, pady=(12, 5), sticky="ew")
        self.create_sidebar_input("Port TWS/Gateway", "4002", "port", 8)
        port_hint = ctk.CTkLabel(
            self.sidebar_frame,
            text="TWS Paper=7497  Live=7496\nGateway Paper=4002  Live=4001",
            font=("Roboto", 10), text_color=COLOR_TEXT_SEC, justify="left"
        )
        port_hint.grid(row=9, column=0, padx=20, pady=(0, 8), sticky="w")

        # Auto-transmit toggle
        self.var_transmit = ctk.BooleanVar(value=False)
        self.chk_transmit = ctk.CTkCheckBox(
            self.sidebar_frame, text="Auto Transmit to Exchange",
            variable=self.var_transmit, font=FONT_MAIN,
            text_color=COLOR_TEXT_PRIMARY,
            fg_color="#2ecc71", hover_color="#27ae60"
        )
        self.chk_transmit.grid(row=10, column=0, padx=20, pady=(8, 0), sticky="w")

        # Connection module (bottom of sidebar)
        self.conn_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.conn_frame.grid(row=11, column=0, padx=20, pady=20, sticky="s")

        self.status_indicator = ctk.CTkLabel(self.conn_frame, text="● OFFLINE",
                                              text_color="#e74c3c", font=FONT_BOLD)
        self.status_indicator.pack(pady=(0, 10))

        self.btn_connect = ctk.CTkButton(
            self.conn_frame, text="CONNECT TWS", font=FONT_BOLD,
            fg_color="#2980b9", hover_color="#3498db", height=45,
            command=self.toggle_connection
        )
        self.btn_connect.pack(fill="x")

        # ==================== MAIN AREA (RIGHT) ====================
        self.main_frame = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)

        self.main_frame.grid_columnconfigure((0, 1), weight=1)
        self.main_frame.grid_rowconfigure((1, 2), weight=1)

        # Header
        self.lbl_main = ctk.CTkLabel(self.main_frame, text="EXECUTION DECK",
                                      font=FONT_TITLE, text_color=COLOR_TEXT_PRIMARY)
        self.lbl_main.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))

        # Macro Buttons
        self.btn_pcs = ctk.CTkButton(
            self.main_frame, text="↗ BULLISH ORB\n\nShoot PCS",
            font=FONT_MACRO, fg_color="#27ae60", hover_color="#2ecc71",
            corner_radius=15, command=lambda: self.execute_trade('PCS')
        )
        self.btn_pcs.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        self.btn_ccs = ctk.CTkButton(
            self.main_frame, text="↘ BEARISH ORB\n\nShoot CCS",
            font=FONT_MACRO, fg_color="#c0392b", hover_color="#e74c3c",
            corner_radius=15, command=lambda: self.execute_trade('CCS')
        )
        self.btn_ccs.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(0, 10))

        self.btn_ic = ctk.CTkButton(
            self.main_frame, text="↔ NEUTRAL RANGE\n\nShoot Iron Condor",
            font=FONT_MACRO, fg_color="#8e44ad", hover_color="#9b59b6",
            corner_radius=15, command=lambda: self.execute_trade('IC')
        )
        self.btn_ic.grid(row=2, column=0, sticky="nsew", padx=(0, 10), pady=(10, 20))

        self.btn_panic = ctk.CTkButton(
            self.main_frame, text="⚠ EXIT ALL POSITIONS ⚠\n\nFlatten Portfolio",
            font=FONT_MACRO, fg_color="#d35400", hover_color="#e67e22",
            corner_radius=15, border_width=2, border_color="#e74c3c"
        )
        self.btn_panic.grid(row=2, column=1, sticky="nsew", padx=(10, 0), pady=(10, 20))

        # Console log
        self.log_box = ctk.CTkTextbox(self.main_frame, height=120,
                                       fg_color=COLOR_PANEL, text_color="#A9CCE3",
                                       font=("Courier", 13))
        self.log_box.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.log("System initialized. Awaiting API connection...")

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def create_sidebar_input(self, label_text, default_val, var_name, row):
        """Create a labelled entry row in the sidebar."""
        frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        frame.grid(row=row, column=0, padx=20, pady=8, sticky="ew")

        lbl = ctk.CTkLabel(frame, text=label_text, font=FONT_MAIN,
                            text_color=COLOR_TEXT_PRIMARY)
        lbl.pack(side="left")

        entry = ctk.CTkEntry(frame, width=60, font=FONT_BOLD, justify="center",
                              fg_color=COLOR_PANEL, border_color="#34495e")
        entry.insert(0, default_val)
        entry.pack(side="right")

        setattr(self, f"val_{var_name}", entry)

    def log(self, msg):
        """Append a message to the on-screen console log."""
        self.log_box.insert(tk.END, "> " + msg + "\n")
        self.log_box.see(tk.END)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def toggle_connection(self):
        """Connect or disconnect from Interactive Brokers."""
        if self.connected:
            if self.engine:
                self.engine.disconnect()
            # Stop the persistent IB event loop
            if hasattr(self, 'ib_loop') and self.ib_loop.is_running():
                self.ib_loop.call_soon_threadsafe(self.ib_loop.stop)
            self.status_indicator.configure(text="● OFFLINE", text_color="#e74c3c")
            self.btn_connect.configure(text="CONNECT TWS", fg_color="#2980b9")
            self.log("Disconnected from Interactive Brokers.")
            self.connected = False
        else:
            self.btn_connect.configure(text="CONNECTING...", fg_color="#f39c12")
            threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        """Background thread: creates a single persistent IB event loop, connects, then keeps it alive."""
        try:
            port = int(self.val_port.get())
        except ValueError:
            self.log("ERROR: Port must be a number (e.g. 7497).")
            self.btn_connect.configure(text="CONNECT TWS", fg_color="#2980b9")
            return

        # Create the ONE event loop that ib_insync will live on for the entire session
        self.ib_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.ib_loop)

        self.engine = IBKREngine(port=port)
        self.log(f"Attempting connection on port {port}...")

        # Run the async connect coroutine on our loop
        success, err = self.ib_loop.run_until_complete(self.engine.connect_async())

        if success:
            self.connected = True
            self.status_indicator.configure(text="● ONLINE", text_color="#2ecc71")
            self.btn_connect.configure(text="DISCONNECT", fg_color="gray30")
            self.log(f"Connected to Interactive Brokers (port {port}).")
            # Keep the loop running indefinitely so ib_insync can receive market data callbacks
            # and we can dispatch coroutines to it from the GUI thread
            self.ib_loop.run_forever()
        else:
            self.engine = None
            self.btn_connect.configure(text="CONNECT TWS", fg_color="#2980b9")
            self.log(f"FAILED: {err}")

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    def execute_trade(self, trade_type: str):
        """
        Read strategy parameters from the UI and dispatch the trade coroutine
        to the shared IB event loop via run_coroutine_threadsafe.
        """
        try:
            qty = int(self.val_qty.get())
            delta = float(self.val_delta.get())
            width = int(self.val_width.get())
            tp_pct = float(self.val_tp.get())
            sl_ratio = float(self.val_sl.get())
            transmit = self.var_transmit.get()
        except ValueError:
            self.log("ERROR: Invalid parameter format. Check inputs.")
            return

        if not self.connected or not self.engine:
            self.log("ERROR: Not connected to IBKR. Connect first.")
            return

        if not hasattr(self, 'ib_loop') or not self.ib_loop.is_running():
            self.log("ERROR: IB event loop is not running. Reconnect.")
            return

        self.log(f"[{trade_type}] Dispatching... finding {delta}Δ strikes (spread={width}pts)...")

        def dispatch():
            """Dispatch trade coroutine to IB loop and report result back to GUI."""
            future = asyncio.run_coroutine_threadsafe(
                self.engine.execute_spread(
                    trade_type, qty, delta, width, tp_pct, sl_ratio, transmit
                ),
                self.ib_loop
            )
            try:
                future.result(timeout=60)
                status = "LIVE" if transmit else "PENDING in TWS (not yet transmitted)"
                self.log(f"[{trade_type}] ✅ Order staged → {status}")
            except Exception as e:
                self.log(f"[{trade_type}] ❌ ERROR: {e}")

        threading.Thread(target=dispatch, daemon=True).start()


if __name__ == "__main__":
    app = SPXTradingPanel()
    app.mainloop()
