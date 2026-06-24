"""
gui
===================
Tkinter-based two-screen GUI for serial/random session management.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Dict

from config import BG_COLOR, LARGE_FONT, TITLE_FONT, BTN_FONT, RESULT_FONT


class SerialExporterApp:
    """Two-screen Tkinter app with MySQL-backed serial/random counters."""

    def __init__(self, root: tk.Tk, db) -> None:  # DatabaseManager type avoided for circular imports
        self.root = root
        self.db = db
        self.root.title("Serial Number Automation")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("560x480")
        self.root.minsize(500, 420)
        self.root.resizable(True, True)

        self._screen1_frame: tk.Frame | None = None
        self._screen2_frame: tk.Frame | None = None
        self._current_session: Dict | None = None
        self._zebra_process = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self._show_screen1()

    # ------------------------------------------------------------------
    # Screen helpers
    # ------------------------------------------------------------------
    def _clear(self) -> None:
        for f in (self._screen1_frame, self._screen2_frame):
            if f is not None:
                f.pack_forget()

    def _show_screen1(self) -> None:
        self._clear()
        self._screen1_frame = self._build_screen1()
        self._screen1_frame.pack(fill="both", expand=True)

    def _show_screen2(self) -> None:
        self._clear()
        if self._screen2_frame is not None:
            self._screen2_frame.pack_forget()
        self._screen2_frame = self._build_screen2()
        self._screen2_frame.pack(fill="both", expand=True)

    def _make_button(self, parent, text: str, command, bg: str = "#0066cc") -> tk.Button:
        return tk.Button(
            parent, text=text, font=BTN_FONT, bg=bg, fg="white",
            padx=20, pady=8, cursor="hand2", command=command,
        )

    # ------------------------------------------------------------------
    # Screen 1 — Request
    # ------------------------------------------------------------------
    def _build_screen1(self) -> tk.Frame:
        frame = tk.Frame(self.root, padx=30, pady=25, bg=BG_COLOR)

        tk.Label(frame, text="Serial Number Automation", font=TITLE_FONT, bg=BG_COLOR).grid(
            row=0, column=0, columnspan=2, pady=(0, 20)
        )

        if not self.db.has_counter():
            tk.Label(
                frame, text="This is the first time running the app.\nEnter the starting values:",
                wraplength=480, justify="left", font=LARGE_FONT, bg=BG_COLOR, fg="#333333"
            ).grid(row=1, column=0, columnspan=2, pady=(0, 15))

            tk.Label(frame, text="Starting serial number:", font=LARGE_FONT, bg=BG_COLOR).grid(
                row=2, column=0, sticky="w", pady=(0, 5)
            )
            self.start_serial_entry = tk.Entry(frame, width=15, font=LARGE_FONT, justify="center")
            self.start_serial_entry.grid(row=2, column=1, sticky="ew", pady=(0, 5))
            self.start_serial_entry.focus_set()

            tk.Label(frame, text="Starting random number:", font=LARGE_FONT, bg=BG_COLOR).grid(
                row=3, column=0, sticky="w", pady=(0, 5)
            )
            self.start_random_entry = tk.Entry(frame, width=15, font=LARGE_FONT, justify="center")
            self.start_random_entry.grid(row=3, column=1, sticky="ew", pady=(0, 5))

            tk.Label(frame, text="Number of labels to print:", font=LARGE_FONT, bg=BG_COLOR).grid(
                row=4, column=0, sticky="w", pady=(10, 15)
            )
            self.qty_entry = tk.Entry(frame, width=15, font=LARGE_FONT, justify="center")
            self.qty_entry.grid(row=4, column=1, sticky="ew", pady=(10, 15))

            self._make_button(frame, "Start Session", self._on_first_start).grid(
                row=5, column=0, columnspan=2, pady=(10, 15)
            )
            self._make_button(frame, "Exit", self._on_exit, bg="#cc3300").grid(
                row=6, column=0, columnspan=2, pady=(0, 5)
            )

            self.screen1_result = tk.Label(frame, text="", wraplength=480, justify="left", font=RESULT_FONT, bg=BG_COLOR)
            self.screen1_result.grid(row=7, column=0, columnspan=2, pady=(0, 5))
        else:
            next_serial = self.db.get_next_serial()
            next_random = self.db.get_next_random()

            tk.Label(
                frame, text=f"Next serial number:  {next_serial:,}",
                wraplength=480, justify="left", font=("Segoe UI", 13, "bold"), bg=BG_COLOR, fg="#006600"
            ).grid(row=1, column=0, columnspan=2, pady=(0, 5))
            tk.Label(
                frame, text=f"Next random number:  {next_random:,}",
                wraplength=480, justify="left", font=("Segoe UI", 13, "bold"), bg=BG_COLOR, fg="#006600"
            ).grid(row=2, column=0, columnspan=2, pady=(0, 15))

            tk.Label(frame, text="Number of labels to print:", font=LARGE_FONT, bg=BG_COLOR).grid(
                row=3, column=0, sticky="w", pady=(0, 15)
            )
            self.qty_entry = tk.Entry(frame, width=15, font=LARGE_FONT, justify="center")
            self.qty_entry.grid(row=3, column=1, sticky="ew", pady=(0, 15))
            self.qty_entry.focus_set()

            btn_frame = tk.Frame(frame, bg=BG_COLOR)
            btn_frame.grid(row=4, column=0, columnspan=2, pady=(10, 15))
            self._make_button(btn_frame, "Start Session", self._on_start_session).pack(side="left", padx=(0, 15))
            self._make_button(btn_frame, "Exit", self._on_exit, bg="#cc3300").pack(side="left")

            self.screen1_result = tk.Label(frame, text="", wraplength=480, justify="left", font=RESULT_FONT, bg=BG_COLOR)
            self.screen1_result.grid(row=5, column=0, columnspan=2, pady=(0, 5))

        frame.columnconfigure(1, weight=1)
        return frame

    # ------------------------------------------------------------------
    def _validate_qty(self) -> int | None:
        qty_raw = self.qty_entry.get().strip()
        if not qty_raw:
            self.screen1_result.config(text="Please enter a number.", fg="red")
            return None
        try:
            qty = int(qty_raw)
        except ValueError:
            self.screen1_result.config(text="Please enter a whole number (e.g. 50).", fg="red")
            return None
        if qty < 1:
            self.screen1_result.config(text="Number must be 1 or more.", fg="red")
            return None
        from config import QUANTITY_WARN_THRESHOLD
        if qty > QUANTITY_WARN_THRESHOLD:
            proceed = messagebox.askyesno(
                "Large Quantity",
                f"You entered a quantity of {qty:,}.\n\nThis will create {qty:,} rows in the CSV file.\nAre you sure you want to continue?",
            )
            if not proceed:
                self.screen1_result.config(text="Cancelled — quantity was too large.", fg="orange")
                return None
        return qty

    # ------------------------------------------------------------------
    def _on_first_start(self) -> None:
        raw_ser = self.start_serial_entry.get().strip()
        if not raw_ser:
            self.screen1_result.config(text="Please enter a starting serial number.", fg="red")
            return
        try:
            start_serial = int(raw_ser)
        except ValueError:
            self.screen1_result.config(text="Starting serial must be a whole number.", fg="red")
            return
        if start_serial < 1:
            self.screen1_result.config(text="Starting serial must be 1 or more.", fg="red")
            return

        raw_ran = self.start_random_entry.get().strip()
        if not raw_ran:
            self.screen1_result.config(text="Please enter a starting random number.", fg="red")
            return
        try:
            start_random = int(raw_ran)
        except ValueError:
            self.screen1_result.config(text="Starting random must be a whole number.", fg="red")
            return
        if start_random < 1:
            self.screen1_result.config(text="Starting random must be 1 or more.", fg="red")
            return

        qty = self._validate_qty()
        if qty is None:
            return

        try:
            self.db.seed_counters(start_serial, start_random)
        except Exception as exc:
            self.screen1_result.config(text=f"Database error: {exc}", fg="red")
            return

        self._do_session(qty)

    def _on_start_session(self) -> None:
        qty = self._validate_qty()
        if qty is None:
            return
        self._do_session(qty)

    # ------------------------------------------------------------------
    def _do_session(self, qty: int) -> None:
        try:
            session = self.db.reserve_range(qty)
        except Exception as exc:
            self.screen1_result.config(text=f"Database error during reservation: {exc}", fg="red")
            return

        from config import SERIAL_STEP, RANDOM_STEP
        serials = list(range(session["serial_range_start"], session["serial_range_end"] + 1))
        randoms = list(range(session["random_range_start"], session["random_range_end"] + 1, RANDOM_STEP))

        try:
            from csv_exporter import write_csv, get_default_export_path
            filepath = get_default_export_path()
            write_csv(serials, randoms, filepath)
        except Exception as exc:
            self.screen1_result.config(
                text=f"CSV write failed (reservation still succeeded): {exc}\nYou may need to void session #{session['session_id']}.",
                fg="red",
            )
            return

        try:
            from zebra_integration import open_zebra_label, zebra_keyboard_sequence
            from config import ZEBRA_LABEL_FILE
            from pathlib import Path
            label_path = Path.cwd() / ZEBRA_LABEL_FILE
            if label_path.exists():
                self._zebra_process = open_zebra_label(str(label_path))
                zebra_keyboard_sequence()
        except Exception:
            pass

        self._current_session = session
        self._current_session["filepath"] = str(filepath)
        self._show_screen2()

    # ------------------------------------------------------------------
    # Screen 2 — Confirm
    # ------------------------------------------------------------------
    def _build_screen2(self) -> tk.Frame:
        frame = tk.Frame(self.root, padx=30, pady=25, bg=BG_COLOR)
        s = self._current_session
        if s is None:
            return frame

        tk.Label(frame, text="Print Confirmation", font=TITLE_FONT, bg=BG_COLOR).grid(
            row=0, column=0, columnspan=2, pady=(0, 15)
        )

        info = (
            f"Session #{s['session_id']} — reserved serials "
            f"{s['serial_range_start']:,} to {s['serial_range_end']:,} "
            f"({s['quantity_requested']:,} labels)"
        )
        tk.Label(frame, text=info, wraplength=480, justify="left", font=LARGE_FONT, bg=BG_COLOR, fg="#333333").grid(
            row=1, column=0, columnspan=2, pady=(0, 10)
        )

        tk.Label(
            frame, text="ZebraDesigner Pro 2 has been opened.\nPrint from print_queue.csv, then come back here.",
            wraplength=480, justify="left", font=RESULT_FONT, bg=BG_COLOR, fg="#0066cc"
        ).grid(row=2, column=0, columnspan=2, pady=(0, 15))

        btn_frame = tk.Frame(frame, bg=BG_COLOR)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(5, 15))
        self._make_button(btn_frame, "Complete", self._on_complete, bg="#008000").pack(side="left", padx=(0, 10))
        self._make_button(btn_frame, "Incomplete", self._on_show_incomplete, bg="#cc8800").pack(side="left", padx=(0, 10))
        self._make_button(btn_frame, "Cancel Session", self._on_void, bg="#cc3300").pack(side="left")

        self._incomplete_frame = tk.Frame(frame, bg=BG_COLOR)
        self._incomplete_frame.grid(row=4, column=0, columnspan=2, pady=(0, 10))
        tk.Label(
            self._incomplete_frame, text="Last serial number that printed successfully:",
            wraplength=480, justify="left", font=LARGE_FONT, bg=BG_COLOR
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.confirm_entry = tk.Entry(self._incomplete_frame, width=15, font=LARGE_FONT, justify="center")
        self.confirm_entry.grid(row=0, column=1, sticky="ew", pady=(0, 10))
        self._make_button(self._incomplete_frame, "Confirm Incomplete", self._on_confirm_incomplete, bg="#008000").grid(
            row=1, column=0, columnspan=2, pady=(5, 5)
        )

        self.screen2_result = tk.Label(frame, text="", wraplength=480, justify="left", font=RESULT_FONT, bg=BG_COLOR)
        self.screen2_result.grid(row=5, column=0, columnspan=2, pady=(0, 5))
        self._incomplete_frame.grid_remove()

        frame.columnconfigure(1, weight=1)
        return frame

    def _on_complete(self) -> None:
        s = self._current_session
        if s is None:
            return
        self._do_confirm(s["serial_range_end"])

    def _on_show_incomplete(self) -> None:
        self._incomplete_frame.grid()
        self.confirm_entry.focus_set()

    def _on_confirm_incomplete(self) -> None:
        s = self._current_session
        if s is None:
            return
        raw = self.confirm_entry.get().strip()
        if not raw:
            self.screen2_result.config(text="Please enter the last serial that printed successfully.", fg="red")
            return
        try:
            last_good = int(raw)
        except ValueError:
            self.screen2_result.config(text="Please enter a whole number.", fg="red")
            return
        self._do_confirm(last_good)

    # ------------------------------------------------------------------
    def _do_confirm(self, last_good: int) -> None:
        s = self._current_session
        if s is None:
            return

        start = s["serial_range_start"]
        end = s["serial_range_end"]
        if last_good < start or last_good > end:
            self.screen2_result.config(
                text=f"Value must be between {start:,} and {end:,} (the range reserved for this session).", fg="red"
            )
            return

        try:
            self.db.confirm_session(s["session_id"], last_good)
        except Exception as exc:
            self.screen2_result.config(text=f"Database error during confirmation: {exc}", fg="red")
            return

        status_text = "confirmed (all labels printed)" if last_good >= end else f"partial (last good: {last_good:,})"
        self.screen2_result.config(text=f"Session #{s['session_id']} {status_text}.", fg="green")

        from zebra_integration import close_zebra
        close_zebra()
        self._zebra_process = None
        self.root.after(1500, self._return_to_screen1)

    # ------------------------------------------------------------------
    def _on_void(self) -> None:
        s = self._current_session
        if s is None:
            return
        proceed = messagebox.askyesno(
            "Cancel Session",
            f"Mark session #{s['session_id']} as cancelled?\n\n"
            f"The reserved serials {s['serial_range_start']:,} to {s['serial_range_end']:,} will be skipped "
            f"(never reused — they become gaps in the sequence).",
        )
        if not proceed:
            return
        try:
            self.db.void_session(s["session_id"])
        except Exception as exc:
            self.screen2_result.config(text=f"Database error during void: {exc}", fg="red")
            return

        self.screen2_result.config(text=f"Session #{s['session_id']} cancelled.", fg="orange")
        from zebra_integration import close_zebra
        close_zebra()
        self._zebra_process = None
        self.root.after(1500, self._return_to_screen1)

    # ------------------------------------------------------------------
    def _on_exit(self) -> None:
        from zebra_integration import close_zebra
        close_zebra()
        self._zebra_process = None
        self.root.destroy()

    def _return_to_screen1(self) -> None:
        self._current_session = None
        self._show_screen1()