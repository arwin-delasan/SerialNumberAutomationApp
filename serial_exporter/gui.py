"""
gui
===================
Tkinter-based two-screen GUI for serial/random session management.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Dict

from config import (
    BG_COLOR, CARD_BG, PRIMARY_COLOR, PRIMARY_DARK, PRIMARY_LIGHT,
    SUCCESS_COLOR, SUCCESS_BG, SUCCESS_BORDER, TEXT_PRIMARY, TEXT_SECONDARY,
    TEXT_MUTED, BORDER_COLOR, SHADOW_COLOR, ERROR_COLOR, WARNING_COLOR,
    LARGE_FONT, TITLE_FONT, BTN_FONT, RESULT_FONT, CARD_TITLE_FONT, DISPLAY_FONT
)


class SerialExporterApp:
    """Two-screen Tkinter app with MySQL-backed serial/random counters."""

    def __init__(self, root: tk.Tk, db) -> None:
        self.root = root
        self.db = db
        self.root.title("Serial Number Automation")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("800x700")
        self.root.minsize(700, 600)
        self.root.resizable(True, True)

        self._screen1_frame: tk.Frame | None = None
        self._screen2_frame: tk.Frame | None = None
        self._current_session: Dict | None = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self.root.bind("<Configure>", self._on_window_resize)
        self._show_screen1()

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

    def _on_window_resize(self, event):
        if event.widget == self.root:
            width = self.root.winfo_width()
            wrap = max(300, width - 140)
            for frame in (self._screen1_frame, self._screen2_frame):
                if frame:
                    for widget in frame.winfo_children():
                        self._update_widget_wrap(widget, wrap)

    def _update_widget_wrap(self, widget, wrap_length):
        if hasattr(widget, 'config'):
            try:
                widget.config(wraplength=wrap_length)
            except:
                pass
        for child in widget.winfo_children():
            self._update_widget_wrap(child, wrap_length)

    def _make_button(self, parent, text: str, command, bg: str = PRIMARY_COLOR, width: int = 20) -> tk.Button:
        return tk.Button(
            parent, text=text, font=BTN_FONT, bg=bg, fg="white",
            padx=20, pady=10, cursor="hand2", command=command, width=width,
            activebackground=PRIMARY_DARK, activeforeground="white",
            relief="flat", borderwidth=0
        )

    def _create_card(self, parent, title: str, value: str) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD_BG, relief="solid", borderwidth=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        card.container = tk.Frame(card, bg=CARD_BG, padx=20, pady=15)
        card.container.pack(fill="both", expand=True)
        
        tk.Label(
            card.container, text=title, font=CARD_TITLE_FONT,
            bg=CARD_BG, fg=TEXT_SECONDARY
        ).pack(anchor="w")
        
        tk.Label(
            card.container, text=value, font=DISPLAY_FONT,
            bg=CARD_BG, fg=SUCCESS_COLOR
        ).pack(anchor="w", pady=(5, 0))
        
        return card

    def _build_screen1(self) -> tk.Frame:
        frame = tk.Frame(self.root, bg=BG_COLOR)

        header_frame = tk.Frame(frame, bg=BG_COLOR)
        header_frame.pack(fill="x", padx=40, pady=(25, 20))
        
        tk.Label(
            header_frame, text="Serial Number Automation",
            font=TITLE_FONT, bg=BG_COLOR, fg=TEXT_PRIMARY
        ).pack(side="left")

        if not self.db.has_counter():
            self._build_initial_setup(frame)
        else:
            self._build_existing_session(frame)

        return frame

    def _build_initial_setup(self, parent: tk.Frame) -> None:
        container = tk.Frame(parent, bg=BG_COLOR)
        container.pack(fill="both", expand=True, padx=40, pady=10)

        tk.Label(
            container, text="Welcome! First Time Setup",
            font=LARGE_FONT, bg=BG_COLOR, fg=TEXT_PRIMARY
        ).pack(anchor="w", pady=(0, 20))

        form_card = tk.Frame(container, bg=CARD_BG, relief="solid", borderwidth=1,
                             highlightbackground=BORDER_COLOR, highlightthickness=1)
        form_card.pack(fill="both", expand=True, pady=(0, 15))
        
        inner_form = tk.Frame(form_card, bg=CARD_BG, padx=25, pady=20)
        inner_form.pack(fill="both", expand=True)

        self._create_form_field(inner_form, "Starting Serial Number:", "start_serial_entry", 0)
        self._create_form_field(inner_form, "Starting Random Number:", "start_random_entry", 1)
        self._create_form_field(inner_form, "Number of Labels to Print:", "qty_entry", 2)

        self.start_serial_entry.focus_set()

        btn_frame = tk.Frame(container, bg=BG_COLOR)
        btn_frame.pack(fill="x")
        self._make_button(btn_frame, "Start Session", self._on_first_start, width=25).pack(side="left")
        self._make_button(btn_frame, "Exit", self._on_exit, bg="#d9363e", width=12).pack(side="right")

        self.screen1_result = tk.Label(container, text="", wraplength=480,
                                       justify="left", font=RESULT_FONT, bg=BG_COLOR, fg=ERROR_COLOR)
        self.screen1_result.pack(pady=(10, 0))

    def _build_existing_session(self, parent: tk.Frame) -> None:
        container = tk.Frame(parent, bg=BG_COLOR)
        container.pack(fill="both", expand=True, padx=40, pady=10)

        tk.Label(
            container, text="Ready to Print",
            font=LARGE_FONT, bg=BG_COLOR, fg=TEXT_PRIMARY
        ).pack(anchor="w", pady=(0, 15))

        cards_frame = tk.Frame(container, bg=BG_COLOR)
        cards_frame.pack(fill="x", pady=(0, 20))
        
        next_serial = self.db.get_next_serial()
        next_random = self.db.get_next_random()
        
        serial_card = self._create_card(cards_frame, "Next Serial Number", f"{next_serial:,}")
        serial_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        random_card = self._create_card(cards_frame, "Next Random Number", f"{next_random:,}")
        random_card.pack(side="right", fill="both", expand=True, padx=(10, 0))

        form_card = tk.Frame(container, bg=CARD_BG, relief="solid", borderwidth=1,
                             highlightbackground=BORDER_COLOR, highlightthickness=1)
        form_card.pack(fill="x", pady=(0, 15))
    
        inner_form = tk.Frame(form_card, bg=CARD_BG, padx=20, pady=15)
        inner_form.pack(fill="x")
        inner_form.columnconfigure(1, weight=1)

        tk.Label(inner_form, text="Number of Labels:", font=LARGE_FONT,
                 bg=CARD_BG, fg=TEXT_PRIMARY).grid(row=0, column=0, sticky="w", pady=(0, 10))
        
        self.qty_entry = tk.Entry(inner_form, width=12, font=LARGE_FONT,
                                   justify="center", relief="solid",
                                   highlightbackground=BORDER_COLOR, highlightthickness=1)
        self.qty_entry.grid(row=0, column=1, sticky="w", padx=(15, 0), pady=(0, 10))
        self.qty_entry.focus_set()

        btn_frame = tk.Frame(container, bg=BG_COLOR)
        btn_frame.pack(fill="x", pady=(5, 10))
        self._make_button(btn_frame, "Start Printing Session", self._on_start_session, width=22).pack(side="left")
        self._make_button(btn_frame, "Exit", self._on_exit, bg="#d9363e", width=12).pack(side="right")

        self.screen1_result = tk.Label(container, text="", wraplength=480,
                                       justify="left", font=RESULT_FONT, bg=BG_COLOR, fg=ERROR_COLOR)
        self.screen1_result.pack(pady=(5, 0))

    def _create_form_field(self, parent, label_text: str, attr_name: str, row: int) -> None:
        tk.Label(parent, text=label_text, font=LARGE_FONT,
                 bg=CARD_BG, fg=TEXT_PRIMARY).grid(row=row*2, column=0, sticky="w",
                                                     pady=(12 if row > 0 else 0, 6))
        
        entry = tk.Entry(parent, width=20, font=LARGE_FONT, justify="center",
                        relief="solid", highlightbackground=BORDER_COLOR, highlightthickness=1)
        entry.grid(row=row*2+1, column=0, pady=(0, 12), sticky="ew")
        
        setattr(self, attr_name, entry)
        parent.columnconfigure(0, weight=1)

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

        self._current_session = session
        self._current_session["filepath"] = str(filepath)
        self._show_screen2()

    def _build_screen2(self) -> tk.Frame:
        frame = tk.Frame(self.root, bg=BG_COLOR)
        s = self._current_session
        if s is None:
            return frame

        header_frame = tk.Frame(frame, bg=BG_COLOR)
        header_frame.pack(fill="x", padx=30, pady=(25, 20))
        
        tk.Label(
            header_frame, text="Print Confirmation",
            font=TITLE_FONT, bg=BG_COLOR, fg=TEXT_PRIMARY
        ).pack(side="left")

        container = tk.Frame(frame, bg=BG_COLOR)
        container.pack(fill="both", expand=True, padx=30, pady=10)

        info_card = tk.Frame(container, bg=CARD_BG, relief="solid", borderwidth=1,
                            highlightbackground=BORDER_COLOR, highlightthickness=1)
        info_card.pack(fill="x", pady=(0, 15))
        
        inner_info = tk.Frame(info_card, bg=CARD_BG, padx=20, pady=15)
        inner_info.pack(fill="x")

        info_text = (
            f"Session #{s['session_id']} — Reserved serials "
            f"{s['serial_range_start']:,} to {s['serial_range_end']:,} "
            f"({s['quantity_requested']:,} labels)"
        )
        tk.Label(
            inner_info, text=info_text, font=LARGE_FONT,
            bg=CARD_BG, fg=TEXT_PRIMARY
        ).pack(anchor="w")

        banner_frame = tk.Frame(container, bg=PRIMARY_LIGHT, relief="solid", borderwidth=1)
        banner_frame.pack(fill="x", pady=(0, 20))
        
        inner_banner = tk.Frame(banner_frame, bg=PRIMARY_LIGHT, padx=15, pady=12)
        inner_banner.pack(fill="x")
        
        tk.Label(
            inner_banner,
            text="Open ZebraDesigner Pro 2, open 'AutomatedZebraPrinter.lbl', and print from 'print_queue.csv'. Then come back here to confirm.",
            font=LARGE_FONT, bg=PRIMARY_LIGHT, fg=PRIMARY_COLOR, justify="left",
            wraplength=500
        ).pack(anchor="w", fill="x")

        btn_frame = tk.Frame(container, bg=BG_COLOR)
        btn_frame.pack(fill="x", pady=(0, 20))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)
        
        tk.Button(btn_frame, text="Complete", font=BTN_FONT, bg="#2e7d32", fg="white",
                  padx=8, pady=5, cursor="hand2", command=self._on_complete,
                  activebackground=PRIMARY_DARK, activeforeground="white",
                  relief="flat", borderwidth=0).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        tk.Button(btn_frame, text="Incomplete", font=BTN_FONT, bg="#e6a817", fg="white",
                  padx=8, pady=5, cursor="hand2", command=self._on_show_incomplete,
                  activebackground=PRIMARY_DARK, activeforeground="white",
                  relief="flat", borderwidth=0).grid(row=0, column=1, padx=4, sticky="ew")
        tk.Button(btn_frame, text="Cancel", font=BTN_FONT, bg="#d9363e", fg="white",
                  padx=8, pady=5, cursor="hand2", command=self._on_void,
                  activebackground=PRIMARY_DARK, activeforeground="white",
                  relief="flat", borderwidth=0).grid(row=0, column=2, padx=(4, 0), sticky="ew")

        self._incomplete_frame = tk.Frame(container, bg=CARD_BG, relief="solid", borderwidth=1,
                                         highlightbackground=BORDER_COLOR, highlightthickness=1)
        
        inner_recovery = tk.Frame(self._incomplete_frame, bg=CARD_BG, padx=20, pady=15)
        inner_recovery.pack(fill="x")
        inner_recovery.columnconfigure(1, weight=1)

        tk.Label(
            inner_recovery, text="Last serial number that printed successfully:",
            font=LARGE_FONT, bg=CARD_BG, fg=TEXT_PRIMARY
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.confirm_entry = tk.Entry(inner_recovery, width=15, font=LARGE_FONT, justify="center",
                                     relief="solid", highlightbackground=BORDER_COLOR, highlightthickness=1)
        self.confirm_entry.grid(row=0, column=1, sticky="w", padx=(15, 0), pady=(0, 10))

        btn_confirm_frame = tk.Frame(inner_recovery, bg=CARD_BG)
        btn_confirm_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0))
        confirm_btn = tk.Button(
            btn_confirm_frame, text="Confirm Incomplete",
            font=BTN_FONT, bg="#2e7d32", fg="white",
            padx=30, pady=12, cursor="hand2", command=self._on_confirm_incomplete,
            activebackground=PRIMARY_DARK, activeforeground="white",
            relief="flat", borderwidth=0, width=25
        )
        confirm_btn.pack()

        self.screen2_result = tk.Label(container, text="", wraplength=480,
                                       justify="left", font=RESULT_FONT, bg=BG_COLOR, fg=ERROR_COLOR)
        self.screen2_result.pack(pady=(5, 0))

        return frame

    def _on_complete(self) -> None:
        self._hide_incomplete()
        s = self._current_session
        if s is None:
            return
        self._do_confirm(s["serial_range_end"])

    def _on_show_incomplete(self) -> None:
        if self._incomplete_frame.winfo_ismapped():
            self._incomplete_frame.pack_forget()
        else:
            self._incomplete_frame.pack(fill="x", pady=(0, 15))
            self.confirm_entry.focus_set()

    def _hide_incomplete(self) -> None:
        self._incomplete_frame.pack_forget()

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

        self.root.after(1500, self._return_to_screen1)

    def _on_void(self) -> None:
        s = self._current_session
        if s is None:
            return
        proceed = messagebox.askyesno(
            "Cancel Session",
            f"Mark session #{s['session_id']} as cancelled?",
        )
        if not proceed:
            return
        try:
            self.db.void_session(s["session_id"])
        except Exception as exc:
            self.screen2_result.config(text=f"Database error during void: {exc}", fg="red")
            return

        self.screen2_result.config(text=f"Session #{s['session_id']} cancelled.", fg="orange")
        self.root.after(1500, self._return_to_screen1)

    def _on_exit(self) -> None:
        self.root.destroy()

    def _return_to_screen1(self) -> None:
        self._current_session = None
        self._show_screen1()