"""
Serial Number Automation
========================
Takes a quantity, atomically reserves both the serial-number range and the
deterministic "random" range (+15 step) from a local SQLite database, writes
both columns to a CSV file (print_queue.csv) for ZebraDesigner Pro 2, and
provides a confirmation screen to track the last successfully printed serial.

No networking, no ORM, no Python random module.  Single-machine desktop tool.
"""

from __future__ import annotations

import csv
import os
import signal
import sqlite3
import subprocess
import time
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

import pyautogui

# ---------------------------------------------------------------------------
# Configurable constants
# ---------------------------------------------------------------------------
SERIAL_COLUMN_HEADER = "SerialNumber"
RANDOM_COLUMN_HEADER = "RandomNumber"
EXPORT_FILENAME = "print_queue.csv"
QUANTITY_WARN_THRESHOLD = 10000

DB_FILENAME = "print_tracker.db"

# Path to the ZebraDesigner Pro 2 label file
ZEBRA_LABEL_FILE = "AutomatedZebraPrinter.lbl"

# Seed values — one step BEFORE the first real values.
SERIAL_SEED = 1024930          # first real serial will be 1024931
RANDOM_SEED = 808041           # first real random will be 808056 (+15)
SERIAL_STEP = 1
RANDOM_STEP = 15


# ===================================================================
# Database layer
# ===================================================================

class DatabaseManager:
    """Wraps SQLite connection; ensures atomic dual-counter reservation."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    def init_db(self) -> None:
        """Create tables if missing.  Does NOT seed — that happens on first use."""
        conn = self.connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS serial_counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_issued_serial INTEGER NOT NULL,
                last_issued_random INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS print_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_range_start INTEGER NOT NULL,
                serial_range_end INTEGER NOT NULL,
                random_range_start INTEGER NOT NULL,
                random_range_end INTEGER NOT NULL,
                quantity_requested INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'issued',
                confirmed_good_through_serial INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS session_rows (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                serial_number INTEGER NOT NULL,
                random_number INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES print_sessions(session_id)
            );
        """)
        conn.commit()

    # ------------------------------------------------------------------
    def has_counter(self) -> bool:
        """Return True if the serial_counter table has been seeded."""
        conn = self.connect()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM serial_counter"
        ).fetchone()
        return row["cnt"] > 0

    # ------------------------------------------------------------------
    def seed_counters(self, starting_serial: int, starting_random: int) -> None:
        """
        Seed both counters one step before the user-supplied starting values.
        Called exactly once on first run.
        """
        conn = self.connect()
        conn.execute(
            "INSERT OR IGNORE INTO serial_counter (id, last_issued_serial, last_issued_random) "
            "VALUES (1, ?, ?)",
            (starting_serial - SERIAL_STEP, starting_random - RANDOM_STEP),
        )
        conn.commit()

    # ------------------------------------------------------------------
    def _read_counters(self, cursor: sqlite3.Cursor) -> tuple[int, int]:
        cursor.execute(
            "SELECT last_issued_serial, last_issued_random FROM serial_counter WHERE id = 1"
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("serial_counter row missing — seed it first")
        return row["last_issued_serial"], row["last_issued_random"]

    # ------------------------------------------------------------------
    def get_next_serial(self) -> int:
        """Return the serial number the next reservation will start from."""
        conn = self.connect()
        cursor = conn.cursor()
        last_serial, _ = self._read_counters(cursor)
        return last_serial + SERIAL_STEP

    def get_next_random(self) -> int:
        """Return the random number the next reservation will start from."""
        conn = self.connect()
        cursor = conn.cursor()
        _, last_random = self._read_counters(cursor)
        return last_random + RANDOM_STEP

    # ------------------------------------------------------------------
    def reserve_range(self, qty: int) -> dict:
        """
        Atomically reserve *qty* rows on both counters.

        Returns a dict with all computed values:
            session_id, serial_range_start, serial_range_end,
            random_range_start, random_range_end, quantity_requested
        """
        conn = self.connect()
        with conn:
            cursor = conn.cursor()

            # --- read current counters ----------------------------------
            last_serial, last_random = self._read_counters(cursor)

            # --- compute new ranges -------------------------------------
            serial_start = last_serial + SERIAL_STEP
            serial_end   = serial_start + qty - 1

            random_start = last_random + RANDOM_STEP
            random_end   = random_start + (qty - 1) * RANDOM_STEP

            # --- insert session row -------------------------------------
            cursor.execute(
                """INSERT INTO print_sessions
                   (serial_range_start, serial_range_end,
                    random_range_start, random_range_end,
                    quantity_requested, status)
                   VALUES (?, ?, ?, ?, ?, 'issued')""",
                (serial_start, serial_end,
                 random_start, random_end, qty),
            )
            session_id = cursor.lastrowid

        return {
            "session_id": session_id,
            "serial_range_start": serial_start,
            "serial_range_end": serial_end,
            "random_range_start": random_start,
            "random_range_end": random_end,
            "quantity_requested": qty,
        }

    # ------------------------------------------------------------------
    def confirm_session(self, session_id: int, last_good_serial: int) -> bool:
        """
        Update a session's status based on the last-good-serial reported.

        Also inserts individual rows into session_rows *only* up to the
        last_good_serial — nothing beyond what actually printed.

        Equal to range_end → 'confirmed'.
        Less than range_end → 'partial'.
        Returns True if the row was found and updated.
        """
        conn = self.connect()
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT serial_range_start, serial_range_end, "
                "       random_range_start "
                "FROM print_sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False

            if last_good_serial >= row["serial_range_end"]:
                status = "confirmed"
            else:
                status = "partial"

            cursor.execute(
                """UPDATE print_sessions
                   SET status = ?,
                       confirmed_good_through_serial = ?,
                       confirmed_at = CURRENT_TIMESTAMP
                   WHERE session_id = ?""",
                (status, last_good_serial, session_id),
            )

            # --- update counters to the last confirmed values -----------
            count = last_good_serial - row["serial_range_start"] + 1
            new_serial = last_good_serial
            new_random = row["random_range_start"] + (count - 1) * RANDOM_STEP

            cursor.execute(
                "UPDATE serial_counter SET last_issued_serial = ?, last_issued_random = ? "
                "WHERE id = 1",
                (new_serial, new_random),
            )

            # --- insert individual rows up to last_good_serial ----------
            for i in range(count):
                cursor.execute(
                    "INSERT INTO session_rows (session_id, serial_number, random_number) "
                    "VALUES (?, ?, ?)",
                    (session_id,
                     row["serial_range_start"] + i,
                     row["random_range_start"] + i * RANDOM_STEP),
                )

        return True

    # ------------------------------------------------------------------
    def void_session(self, session_id: int) -> bool:
        """Mark a session as voided (nothing printed)."""
        conn = self.connect()
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE print_sessions
                   SET status = 'voided',
                       confirmed_at = CURRENT_TIMESTAMP
                   WHERE session_id = ? AND status = 'issued'""",
                (session_id,),
            )
            return cursor.rowcount > 0


# ===================================================================
# CSV export helper
# ===================================================================

def write_csv(serial_numbers: list[int],
              random_numbers: list[int],
              filepath: Path) -> None:
    """
    Write both columns to a CSV file, fully overwriting whatever was there.
    """
    with open(str(filepath), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([SERIAL_COLUMN_HEADER, RANDOM_COLUMN_HEADER])
        for s, r in zip(serial_numbers, random_numbers, strict=True):
            writer.writerow([s, r])


# ===================================================================
# ZebraDesigner Pro 2 launcher
# ===================================================================

def _zebra_keyboard_sequence() -> None:
    """
    After Zebra opens:
    1. Wait for demo modal, Enter to dismiss it
    2. Wait, Enter to press OK
    3. Wait, Ctrl+R to trigger print
    4. Wait, Enter to confirm preview
    """
    try:
        time.sleep(3)
        pyautogui.press('enter')      # dismiss demo modal
        time.sleep(2)
        pyautogui.press('enter')      # press OK
        time.sleep(2)
        pyautogui.hotkey('ctrl', 'r') # trigger print
        time.sleep(2)
        pyautogui.press('enter')      # confirm preview
    except Exception:
        pass


def _open_zebra_label(label_path: Path) -> subprocess.Popen | None:
    """Open the .lbl file in ZebraDesigner Pro 2 via file association."""
    try:
        return subprocess.Popen(
            ["cmd", "/c", "start", "", str(label_path)],
            shell=True,
        )
    except Exception:
        return None


def _close_zebra() -> None:
    """Try to kill any running ZebraDesigner Pro 2 processes."""
    for name in [
        "ZDesigner.exe",
        "ZDesignerPro.exe",
        "ZebraDesigner.exe",
        "ZebraDesignerPro.exe",
        "ZDPro2.exe",
    ]:
        try:
            subprocess.run(
                ["taskkill", "/f", "/im", name],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass


# ===================================================================
# Tkinter GUI
# ===================================================================

BG_COLOR = "#f0f0f0"
LARGE_FONT = ("Segoe UI", 12)
TITLE_FONT = ("Segoe UI", 14, "bold")
BTN_FONT = ("Segoe UI", 12, "bold")
RESULT_FONT = ("Segoe UI", 11)


class SerialExporterApp:
    """Two-screen Tkinter app with SQLite-backed serial/random counters."""

    def __init__(self, root: tk.Tk, db: DatabaseManager) -> None:
        self.root = root
        self.db = db
        self.root.title("Serial Number Automation")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("560x480")
        self.root.minsize(500, 420)
        self.root.resizable(True, True)

        # --- frames ----------------------------------------------------
        self._screen1_frame: tk.Frame | None = None
        self._screen2_frame: tk.Frame | None = None

        # --- session data carried between screens ----------------------
        self._current_session: dict | None = None

        # --- Zebra process handle --------------------------------------
        self._zebra_process: subprocess.Popen | None = None

        # Close Zebra when user clicks the X button
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
        # Always rebuild to refresh the counter display
        self._screen1_frame = self._build_screen1()
        self._screen1_frame.pack(fill="both", expand=True)

    def _show_screen2(self) -> None:
        self._clear()
        if self._screen2_frame is not None:
            self._screen2_frame.pack_forget()
        self._screen2_frame = self._build_screen2()
        self._screen2_frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    def _make_button(self, parent: tk.Widget, text: str,
                     command, bg: str = "#0066cc") -> tk.Button:
        return tk.Button(
            parent, text=text, font=BTN_FONT,
            bg=bg, fg="white",
            padx=20, pady=8, cursor="hand2",
            command=command,
        )

    # ------------------------------------------------------------------
    # Screen 1 — Request
    # ------------------------------------------------------------------
    def _build_screen1(self) -> tk.Frame:
        frame = tk.Frame(self.root, padx=30, pady=25, bg=BG_COLOR)

        # Title
        tk.Label(
            frame, text="Serial Number Automation",
            font=TITLE_FONT, bg=BG_COLOR
        ).grid(row=0, column=0, columnspan=2, pady=(0, 20))

        if not self.db.has_counter():
            # ---- FIRST RUN: ask for starting serial --------------------
            tk.Label(
                frame,
                text="This is the first time running the app.\n"
                     "Enter the starting values:",
                wraplength=480, justify="left",
                font=LARGE_FONT, bg=BG_COLOR, fg="#333333"
            ).grid(row=1, column=0, columnspan=2, pady=(0, 15))

            tk.Label(
                frame, text="Starting serial number:",
                font=LARGE_FONT, bg=BG_COLOR
            ).grid(row=2, column=0, sticky="w", pady=(0, 5))
            self.start_serial_entry = tk.Entry(
                frame, width=15, font=LARGE_FONT, justify="center"
            )
            self.start_serial_entry.grid(row=2, column=1, sticky="ew", pady=(0, 5))
            self.start_serial_entry.focus_set()

            tk.Label(
                frame, text="Starting random number:",
                font=LARGE_FONT, bg=BG_COLOR
            ).grid(row=3, column=0, sticky="w", pady=(0, 5))
            self.start_random_entry = tk.Entry(
                frame, width=15, font=LARGE_FONT, justify="center"
            )
            self.start_random_entry.grid(row=3, column=1, sticky="ew", pady=(0, 5))

            tk.Label(
                frame, text="Number of labels to print:",
                font=LARGE_FONT, bg=BG_COLOR
            ).grid(row=4, column=0, sticky="w", pady=(10, 15))
            self.qty_entry = tk.Entry(
                frame, width=15, font=LARGE_FONT, justify="center"
            )
            self.qty_entry.grid(row=4, column=1, sticky="ew", pady=(10, 15))

            btn = self._make_button(
                frame, "Start Session", self._on_first_start
            )
            btn.grid(row=5, column=0, columnspan=2, pady=(10, 15))

            # Exit button
            exit_btn = self._make_button(
                frame, "Exit", self._on_exit, bg="#cc3300"
            )
            exit_btn.grid(row=6, column=0, columnspan=2, pady=(0, 5))

            self.screen1_result = tk.Label(
                frame, text="", wraplength=480, justify="left",
                font=RESULT_FONT, bg=BG_COLOR
            )
            self.screen1_result.grid(row=7, column=0, columnspan=2, pady=(0, 5))

        else:
            # ---- SUBSEQUENT RUNS: show next serial & random, ask for quantity ---
            next_serial = self.db.get_next_serial()
            next_random = self.db.get_next_random()
            tk.Label(
                frame,
                text=f"Next serial number:  {next_serial:,}",
                wraplength=480, justify="left",
                font=("Segoe UI", 13, "bold"), bg=BG_COLOR, fg="#006600",
            ).grid(row=1, column=0, columnspan=2, pady=(0, 5))
            tk.Label(
                frame,
                text=f"Next random number:  {next_random:,}",
                wraplength=480, justify="left",
                font=("Segoe UI", 13, "bold"), bg=BG_COLOR, fg="#006600",
            ).grid(row=2, column=0, columnspan=2, pady=(0, 15))

            tk.Label(
                frame, text="Number of labels to print:",
                font=LARGE_FONT, bg=BG_COLOR
            ).grid(row=3, column=0, sticky="w", pady=(0, 15))
            self.qty_entry = tk.Entry(
                frame, width=15, font=LARGE_FONT, justify="center"
            )
            self.qty_entry.grid(row=3, column=1, sticky="ew", pady=(0, 15))
            self.qty_entry.focus_set()

            # Buttons row
            btn_frame = tk.Frame(frame, bg=BG_COLOR)
            btn_frame.grid(row=4, column=0, columnspan=2, pady=(10, 15))
            start_btn = self._make_button(
                btn_frame, "Start Session", self._on_start_session
            )
            start_btn.pack(side="left", padx=(0, 15))
            exit_btn = self._make_button(
                btn_frame, "Exit", self._on_exit, bg="#cc3300"
            )
            exit_btn.pack(side="left")

            self.screen1_result = tk.Label(
                frame, text="", wraplength=480, justify="left",
                font=RESULT_FONT, bg=BG_COLOR
            )
            self.screen1_result.grid(row=5, column=0, columnspan=2, pady=(0, 5))

        frame.columnconfigure(1, weight=1)
        return frame

    # ------------------------------------------------------------------
    def _validate_qty(self) -> int | None:
        """Validate the quantity field and return it, or None on error."""
        qty_raw = self.qty_entry.get().strip()
        if not qty_raw:
            self.screen1_result.config(text="Please enter a number.", fg="red")
            return None
        try:
            qty = int(qty_raw)
        except ValueError:
            self.screen1_result.config(
                text="Please enter a whole number (e.g. 50).", fg="red"
            )
            return None
        if qty < 1:
            self.screen1_result.config(
                text="Number must be 1 or more.", fg="red"
            )
            return None
        if qty > QUANTITY_WARN_THRESHOLD:
            proceed = messagebox.askyesno(
                "Large Quantity",
                f"You entered a quantity of {qty:,}.\n\n"
                f"This will create {qty:,} rows in the CSV file.\n"
                f"Are you sure you want to continue?",
            )
            if not proceed:
                self.screen1_result.config(
                    text="Cancelled — quantity was too large.",
                    fg="orange",
                )
                return None
        return qty

    # ------------------------------------------------------------------
    def _on_first_start(self) -> None:
        """First-run: seed the DB with the user's starting values, then proceed."""
        # --- Validate serial -------------------------------------------------
        raw_ser = self.start_serial_entry.get().strip()
        if not raw_ser:
            self.screen1_result.config(
                text="Please enter a starting serial number.", fg="red"
            )
            return
        try:
            start_serial = int(raw_ser)
        except ValueError:
            self.screen1_result.config(
                text="Starting serial must be a whole number.", fg="red"
            )
            return
        if start_serial < 1:
            self.screen1_result.config(
                text="Starting serial must be 1 or more.", fg="red"
            )
            return

        # --- Validate random -------------------------------------------------
        raw_ran = self.start_random_entry.get().strip()
        if not raw_ran:
            self.screen1_result.config(
                text="Please enter a starting random number.", fg="red"
            )
            return
        try:
            start_random = int(raw_ran)
        except ValueError:
            self.screen1_result.config(
                text="Starting random must be a whole number.", fg="red"
            )
            return
        if start_random < 1:
            self.screen1_result.config(
                text="Starting random must be 1 or more.", fg="red"
            )
            return

        qty = self._validate_qty()
        if qty is None:
            return

        # Seed the counters
        try:
            self.db.seed_counters(start_serial, start_random)
        except Exception as exc:
            self.screen1_result.config(
                text=f"Database error: {exc}", fg="red"
            )
            return

        # Now proceed with the session
        self._do_session(qty)

    # ------------------------------------------------------------------
    def _on_start_session(self) -> None:
        """Subsequent runs: just validate qty and proceed."""
        qty = self._validate_qty()
        if qty is None:
            return
        self._do_session(qty)

    # ------------------------------------------------------------------
    def _do_session(self, qty: int) -> None:
        """Reserve, export CSV, launch Zebra, go to Screen 2."""
        # --- Atomic reservation ----------------------------------------
        try:
            session = self.db.reserve_range(qty)
        except Exception as exc:
            self.screen1_result.config(
                text=f"Database error during reservation: {exc}", fg="red"
            )
            return

        # --- CSV export ------------------------------------------------
        serials = list(range(
            session["serial_range_start"],
            session["serial_range_end"] + 1,
        ))
        randoms = list(range(
            session["random_range_start"],
            session["random_range_end"] + 1,
            RANDOM_STEP,
        ))

        filepath = Path.cwd() / EXPORT_FILENAME
        try:
            write_csv(serials, randoms, filepath)
        except Exception as exc:
            self.screen1_result.config(
                text=f"CSV write failed (reservation still succeeded): {exc}"
                     f"\nYou may need to void session #{session['session_id']}.",
                fg="red",
            )
            return

        # --- Launch ZebraDesigner Pro 2 --------------------------------
        label_path = Path.cwd() / ZEBRA_LABEL_FILE
        if label_path.exists():
            self._zebra_process = _open_zebra_label(label_path)
            _zebra_keyboard_sequence()

        # --- Store session data for Screen 2 ---------------------------
        self._current_session = session
        self._current_session["filepath"] = filepath
        self._show_screen2()

    # ------------------------------------------------------------------
    # Screen 2 — Confirm
    # ------------------------------------------------------------------
    def _build_screen2(self) -> tk.Frame:
        frame = tk.Frame(self.root, padx=30, pady=25, bg=BG_COLOR)
        s = self._current_session
        if s is None:
            return frame

        # Title
        tk.Label(
            frame, text="Print Confirmation",
            font=TITLE_FONT, bg=BG_COLOR
        ).grid(row=0, column=0, columnspan=2, pady=(0, 15))

        # Session info
        info = (
            f"Session #{s['session_id']} — reserved serials "
            f"{s['serial_range_start']:,} to {s['serial_range_end']:,} "
            f"({s['quantity_requested']:,} labels)"
        )
        tk.Label(
            frame, text=info, wraplength=480, justify="left",
            font=LARGE_FONT, bg=BG_COLOR, fg="#333333"
        ).grid(row=1, column=0, columnspan=2, pady=(0, 10))

        # Instruction
        tk.Label(
            frame,
            text="ZebraDesigner Pro 2 has been opened.\n"
                 "Print from print_queue.csv, then come back here.",
            wraplength=480, justify="left",
            font=RESULT_FONT, bg=BG_COLOR, fg="#0066cc"
        ).grid(row=2, column=0, columnspan=2, pady=(0, 15))

        # Buttons row — 3 choices
        btn_frame = tk.Frame(frame, bg=BG_COLOR)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(5, 15))
        complete_btn = self._make_button(
            btn_frame, "Complete", self._on_complete, bg="#008000"
        )
        complete_btn.pack(side="left", padx=(0, 10))
        incomplete_btn = self._make_button(
            btn_frame, "Incomplete", self._on_show_incomplete, bg="#cc8800"
        )
        incomplete_btn.pack(side="left", padx=(0, 10))
        void_btn = self._make_button(
            btn_frame, "Cancel Session", self._on_void, bg="#cc3300"
        )
        void_btn.pack(side="left")

        # Hidden incomplete-entry row (shown only on demand)
        self._incomplete_frame = tk.Frame(frame, bg=BG_COLOR)
        self._incomplete_frame.grid(row=4, column=0, columnspan=2, pady=(0, 10))
        tk.Label(
            self._incomplete_frame,
            text="Last serial number that printed successfully:",
            wraplength=480, justify="left",
            font=LARGE_FONT, bg=BG_COLOR
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.confirm_entry = tk.Entry(
            self._incomplete_frame, width=15, font=LARGE_FONT, justify="center"
        )
        self.confirm_entry.grid(row=0, column=1, sticky="ew", pady=(0, 10))
        confirm_btn2 = self._make_button(
            self._incomplete_frame, "Confirm Incomplete",
            self._on_confirm_incomplete, bg="#008000"
        )
        confirm_btn2.grid(row=1, column=0, columnspan=2, pady=(5, 5))

        # Result message
        self.screen2_result = tk.Label(
            frame, text="", wraplength=480, justify="left",
            font=RESULT_FONT, bg=BG_COLOR
        )
        self.screen2_result.grid(row=5, column=0, columnspan=2, pady=(0, 5))

        # Hide incomplete frame by default
        self._incomplete_frame.grid_remove()

        frame.columnconfigure(1, weight=1)
        return frame

    # ------------------------------------------------------------------
    def _on_complete(self) -> None:
        """All labels printed — confirm up to serial_range_end."""
        s = self._current_session
        if s is None:
            return
        self._do_confirm(s["serial_range_end"])

    def _on_show_incomplete(self) -> None:
        """Show the serial entry field for partial completion."""
        self._incomplete_frame.grid()
        self.confirm_entry.focus_set()

    def _on_confirm_incomplete(self) -> None:
        """Validate and submit the incomplete entry."""
        s = self._current_session
        if s is None:
            return

        raw = self.confirm_entry.get().strip()
        if not raw:
            self.screen2_result.config(
                text="Please enter the last serial that printed successfully.",
                fg="red",
            )
            return
        try:
            last_good = int(raw)
        except ValueError:
            self.screen2_result.config(
                text="Please enter a whole number.", fg="red"
            )
            return

        self._do_confirm(last_good)

    # ------------------------------------------------------------------
    def _do_confirm(self, last_good: int) -> None:
        """Shared confirmation logic — updates DB, closes Zebra, returns."""
        s = self._current_session
        if s is None:
            return

        start = s["serial_range_start"]
        end = s["serial_range_end"]
        if last_good < start or last_good > end:
            self.screen2_result.config(
                text=f"Value must be between {start:,} and {end:,} "
                     f"(the range reserved for this session).",
                fg="red",
            )
            return

        try:
            self.db.confirm_session(s["session_id"], last_good)
        except Exception as exc:
            self.screen2_result.config(
                text=f"Database error during confirmation: {exc}", fg="red"
            )
            return

        if last_good >= end:
            status_text = "confirmed (all labels printed)"
        else:
            status_text = f"partial (last good: {last_good:,})"

        self.screen2_result.config(
            text=f"Session #{s['session_id']} {status_text}.",
            fg="green",
        )

        # Close Zebra and return to Screen 1
        _close_zebra()
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
            f"The reserved serials {s['serial_range_start']:,} to "
            f"{s['serial_range_end']:,} will be skipped "
            f"(never reused — they become gaps in the sequence).",
        )
        if not proceed:
            return

        try:
            self.db.void_session(s["session_id"])
        except Exception as exc:
            self.screen2_result.config(
                text=f"Database error during void: {exc}", fg="red"
            )
            return

        self.screen2_result.config(
            text=f"Session #{s['session_id']} cancelled.",
            fg="orange",
        )

        # Close Zebra and return to Screen 1
        _close_zebra()
        self._zebra_process = None
        self.root.after(1500, self._return_to_screen1)

    # ------------------------------------------------------------------
    def _on_exit(self) -> None:
        """Close ZebraDesigner Pro 2 and exit the app."""
        _close_zebra()
        self._zebra_process = None
        self.root.destroy()

    # ------------------------------------------------------------------
    def _return_to_screen1(self) -> None:
        self._current_session = None
        self._show_screen1()


# ===================================================================
# Entry point
# ===================================================================

def main() -> None:
    db = DatabaseManager(Path.cwd() / DB_FILENAME)
    db.init_db()

    root = tk.Tk()
    app = SerialExporterApp(root, db)
    try:
        root.mainloop()
    finally:
        db.close()


if __name__ == "__main__":
    main()