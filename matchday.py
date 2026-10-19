"""
MatchDay Manager - a football match scoreboard and tactics board built with Tkinter.

Features
  * Scoreboard with editable team names, goal buttons and a match clock (after())
  * Tactics board on a Canvas: 22 draggable players and three formation presets
  * Event log (goals, cards, substitutions ...) - ONE list of events drives the
    score, the log, the live stats chart and the database
  * Live Stats tab: a bar chart drawn on a Canvas that redraws itself
  * SQLite match history with a sortable Treeview window
  * Menu bar, keyboard shortcuts, message boxes, text summary export
"""
import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

# ---------- colours and constants ----------
BG = "#0f2a1d"
PANEL = "#16382a"
PITCH = "#2e8b57"
LINE = "#f2f2f2"
HOME_COL = "#1e88e5"
AWAY_COL = "#e53935"
ACCENT = "#ffd54f"
DARK = "#0b1f15"

PITCH_W, PITCH_H = 560, 360
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matchday.db")

# formation = list of (x, y) as a fraction of the pitch, for the HOME side (left to right)
FORMATIONS = {
    "4-4-2": [(0.06, 0.5)]
             + [(0.20, y) for y in (0.15, 0.38, 0.62, 0.85)]
             + [(0.36, y) for y in (0.15, 0.38, 0.62, 0.85)]
             + [(0.46, y) for y in (0.35, 0.65)],
    "4-3-3": [(0.06, 0.5)]
             + [(0.20, y) for y in (0.15, 0.38, 0.62, 0.85)]
             + [(0.34, y) for y in (0.25, 0.5, 0.75)]
             + [(0.46, y) for y in (0.2, 0.5, 0.8)],
    "3-5-2": [(0.06, 0.5)]
             + [(0.20, y) for y in (0.25, 0.5, 0.75)]
             + [(0.34, y) for y in (0.1, 0.3, 0.5, 0.7, 0.9)]
             + [(0.46, y) for y in (0.35, 0.65)],
}
EVENT_TYPES = ["Yellow Card", "Red Card", "Substitution", "Foul",
               "Corner", "Offside", "Injury"]


def describe(event, home, away):
    """Turn one event dictionary into a line of text for the log."""
    name = home if event["team"] == "home" else away
    stamp = f"{event['secs'] // 60:02d}'"
    if event["kind"] == "Goal":
        return f"{stamp}  GOAL! {name}"
    return f"{stamp}  {event['kind']} - {name} #{event['player']}"


# ======================================================================
# Database layer (sqlite3)
# ======================================================================
class MatchDB:
    """Stores finished matches. Two tables: matches (1) --- (many) events."""

    def __init__(self, path):
        self.path = path
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS matches(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    played_at TEXT, home TEXT, away TEXT,
                    home_score INTEGER, away_score INTEGER, duration INTEGER);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
                    secs INTEGER, team TEXT, kind TEXT, player INTEGER);
            """)
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")      # needed for ON DELETE CASCADE
        return conn

    def save_match(self, home, away, home_score, away_score, duration, events):
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO matches(played_at, home, away, home_score, away_score, duration) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M"), home, away,
                 home_score, away_score, duration))
            match_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO events(match_id, secs, team, kind, player) VALUES (?, ?, ?, ?, ?)",
                [(match_id, e["secs"], e["team"], e["kind"], e["player"]) for e in events])
            conn.commit()
            return match_id
        finally:
            conn.close()

    def list_matches(self):
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT id, played_at, home, home_score, away_score, away, duration "
                "FROM matches ORDER BY id DESC").fetchall()
        finally:
            conn.close()

    def get_events(self, match_id):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT secs, team, kind, player FROM events WHERE match_id = ? ORDER BY id",
                (match_id,)).fetchall()
        finally:
            conn.close()
        return [{"secs": s, "team": t, "kind": k, "player": p} for s, t, k, p in rows]

    def delete_match(self, match_id):
        conn = self._connect()
        try:
            conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            conn.commit()
        finally:
            conn.close()


# ======================================================================
# History window (second Toplevel window with a Treeview)
# ======================================================================
class HistoryWindow(tk.Toplevel):
    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.names = {}            # iid -> (home, away)
        self.sort_state = {}
        self.title("Match History")
        self.geometry("640x470")
        self.configure(bg=BG)
        self.transient(parent)

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 6))
        columns = ("when", "home", "score", "away", "time")
        self.tree = ttk.Treeview(top, columns=columns, show="headings", height=8,
                                 selectmode="browse")
        for col, text, width, anchor in (("when", "Date", 130, "w"), ("home", "Home", 140, "w"),
                                         ("score", "Score", 60, "center"),
                                         ("away", "Away", 140, "w"), ("time", "Time", 60, "center")):
            self.tree.heading(col, text=text, command=lambda c=col: self.sort_by(c))
            self.tree.column(col, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.show_events)

        tk.Label(self, text="Events of the selected match  (click a column heading to sort)",
                 bg=BG, fg=ACCENT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12)
        self.events_list = tk.Listbox(self, bg=DARK, fg="white", font=("Consolas", 10),
                                      activestyle="none", height=9)
        self.events_list.pack(fill="both", expand=True, padx=12, pady=6)

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(bottom, text="Delete Match", command=self.delete_selected).pack(side="left")
        tk.Button(bottom, text="Close", command=self.destroy).pack(side="right")
        self.load()

    def load(self):
        self.tree.delete(*self.tree.get_children())
        self.names.clear()
        for mid, when, home, hs, aws, away, secs in self.db.list_matches():
            iid = str(mid)
            self.names[iid] = (home, away)
            self.tree.insert("", "end", iid=iid,
                             values=(when, home, f"{hs} - {aws}", away,
                                     f"{secs // 60:02d}:{secs % 60:02d}"))
        self.events_list.delete(0, "end")

    def show_events(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        home, away = self.names[selection[0]]
        self.events_list.delete(0, "end")
        for e in self.db.get_events(int(selection[0])):
            self.events_list.insert("end", describe(e, home, away))

    def sort_by(self, col):
        reverse = self.sort_state.get(col, False)
        items = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children("")]
        items.sort(reverse=reverse)
        for index, (_, iid) in enumerate(items):
            self.tree.move(iid, "", index)
        self.sort_state[col] = not reverse

    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Delete match", "Select a match first.", parent=self)
            return
        if messagebox.askyesno("Delete match", "Delete this match and its events?", parent=self):
            self.db.delete_match(int(selection[0]))
            self.load()


# ======================================================================
# Main application window
# ======================================================================
class MatchDayManager(tk.Tk):
    def __init__(self, db_path=DB_FILE):
        super().__init__()
        self.title("MatchDay Manager")
        self.geometry("980x660")
        self.configure(bg=BG)
        self.minsize(940, 620)

        # ----- state -----
        self.db = MatchDB(db_path)
        self.events = []                  # the single source of truth for a match
        self.seconds = 0
        self.running = False
        self.timer_job = None
        self.drag_item = None
        self.drag_group = []
        self.last = (0, 0)
        self.history_win = None

        self.home_name = tk.StringVar(value="Home FC")
        self.away_name = tk.StringVar(value="Away United")
        self.home_form = tk.StringVar(value="4-4-2")
        self.away_form = tk.StringVar(value="4-4-2")
        self.event_type = tk.StringVar(value=EVENT_TYPES[0])
        self.event_team = tk.StringVar(value="Home")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 5), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)],
                  foreground=[("selected", "black")])

        self.build_menu()
        self.build_scoreboard()
        self.build_body()
        self.bind_keys()
        self.draw_pitch()
        self.place_players()
        # redraw everything whenever a team name is edited
        self.home_name.trace_add("write", lambda *args: self.refresh_all())
        self.away_name.trace_add("write", lambda *args: self.refresh_all())
        self.refresh_all()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Summary...", accelerator="Ctrl+S", command=self.save_summary)
        file_menu.add_command(label="Save to History", accelerator="F2", command=self.save_to_history)
        file_menu.add_command(label="Match History...", accelerator="Ctrl+H", command=self.open_history)
        file_menu.add_separator()
        file_menu.add_command(label="New Match", accelerator="Ctrl+N", command=self.new_match)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=file_menu)

        match_menu = tk.Menu(menubar, tearoff=0)
        match_menu.add_command(label="Start / Pause", accelerator="Space", command=self.toggle_clock)
        match_menu.add_command(label="Reset Player Positions", command=self.place_players)
        menubar.add_cascade(label="Match", menu=match_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def build_scoreboard(self):
        board = tk.Frame(self, bg=PANEL, bd=0, highlightthickness=2, highlightbackground=ACCENT)
        board.pack(fill="x", padx=14, pady=(14, 8))
        board.columnconfigure((0, 4), weight=1)

        home = tk.Frame(board, bg=PANEL)
        home.grid(row=0, column=0, padx=10, pady=8)
        tk.Entry(home, textvariable=self.home_name, font=("Segoe UI", 14, "bold"), justify="center",
                 width=14, bg=HOME_COL, fg="white", insertbackground="white", relief="flat"
                 ).pack(pady=(0, 6))
        hb = tk.Frame(home, bg=PANEL)
        hb.pack()
        tk.Button(hb, text="-", width=3, command=lambda: self.change_score("home", -1)
                  ).pack(side="left", padx=2)
        tk.Button(hb, text="+ GOAL", width=9, bg=HOME_COL, fg="white",
                  command=lambda: self.change_score("home", 1)).pack(side="left", padx=2)

        self.home_lbl = tk.Label(board, text="0", font=("Consolas", 48, "bold"), bg=PANEL, fg="white", width=2)
        self.home_lbl.grid(row=0, column=1)

        centre = tk.Frame(board, bg=PANEL)
        centre.grid(row=0, column=2, padx=14)
        self.clock_lbl = tk.Label(centre, text="00:00", font=("Consolas", 30, "bold"),
                                  bg="black", fg=ACCENT, width=7)
        self.clock_lbl.pack(pady=(4, 4))
        cb = tk.Frame(centre, bg=PANEL)
        cb.pack()
        self.start_btn = tk.Button(cb, text="Start", width=8, command=self.toggle_clock)
        self.start_btn.pack(side="left", padx=2)
        tk.Button(cb, text="Reset", width=8, command=self.reset_clock).pack(side="left", padx=2)

        self.away_lbl = tk.Label(board, text="0", font=("Consolas", 48, "bold"), bg=PANEL, fg="white", width=2)
        self.away_lbl.grid(row=0, column=3)

        away = tk.Frame(board, bg=PANEL)
        away.grid(row=0, column=4, padx=10, pady=8)
        tk.Entry(away, textvariable=self.away_name, font=("Segoe UI", 14, "bold"), justify="center",
                 width=14, bg=AWAY_COL, fg="white", insertbackground="white", relief="flat"
                 ).pack(pady=(0, 6))
        ab = tk.Frame(away, bg=PANEL)
        ab.pack()
        tk.Button(ab, text="-", width=3, command=lambda: self.change_score("away", -1)
                  ).pack(side="left", padx=2)
        tk.Button(ab, text="+ GOAL", width=9, bg=AWAY_COL, fg="white",
                  command=lambda: self.change_score("away", 1)).pack(side="left", padx=2)

    def build_body(self):
        # status bar is packed FIRST (side=bottom) so the expanding body cannot squeeze it out
        self.status = tk.Label(self, text="Ready. Press Space to start the clock.",
                               anchor="w", bg="black", fg="white", padx=8)
        self.status.pack(fill="x", side="bottom")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # ---- pitch (left) ----
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", anchor="n")

        head = tk.Frame(left, bg=BG)
        head.pack(fill="x", pady=(0, 4))
        tk.Label(head, text="Tactics Board", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        for label, var in (("Away", self.away_form), ("Home", self.home_form)):
            box = ttk.Combobox(head, textvariable=var, values=list(FORMATIONS), state="readonly", width=6)
            box.pack(side="right", padx=(0, 4))
            box.bind("<<ComboboxSelected>>", self.on_formation)
            tk.Label(head, text=label, bg=BG, fg="white", font=("Segoe UI", 9)).pack(side="right", padx=(8, 4))

        self.canvas = tk.Canvas(left, width=PITCH_W, height=PITCH_H, bg=PITCH,
                                highlightthickness=2, highlightbackground=LINE)
        self.canvas.pack()
        self.canvas.tag_bind("player", "<ButtonPress-1>", self.on_press)
        self.canvas.tag_bind("player", "<B1-Motion>", self.on_drag)
        self.canvas.tag_bind("player", "<ButtonRelease-1>", self.on_release)
        self.canvas.tag_bind("player", "<Enter>", lambda e: self.canvas.config(cursor="hand2"))
        self.canvas.tag_bind("player", "<Leave>", lambda e: self.canvas.config(cursor=""))

        self.coord_lbl = tk.Label(left, text="Hover or drag a player", bg=BG, fg="white", font=("Segoe UI", 9))
        self.coord_lbl.pack(anchor="w", pady=(4, 0))

        # ---- notebook with two tabs (right) ----
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        tab_events = tk.Frame(self.notebook, bg=PANEL, padx=10, pady=10)
        tab_stats = tk.Frame(self.notebook, bg=PANEL, padx=6, pady=6)
        self.notebook.add(tab_events, text="Events")
        self.notebook.add(tab_stats, text="Live Stats")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.draw_stats())

        form = tk.Frame(tab_events, bg=PANEL)
        form.pack(fill="x", pady=(0, 6))
        ttk.Combobox(form, textvariable=self.event_team, values=["Home", "Away"],
                     state="readonly", width=7).grid(row=0, column=0, padx=2)
        ttk.Combobox(form, textvariable=self.event_type, values=EVENT_TYPES,
                     state="readonly", width=13).grid(row=0, column=1, padx=2)
        tk.Label(form, text="Player #", bg=PANEL, fg="white").grid(row=1, column=0, pady=4)
        self.player_no = tk.Spinbox(form, from_=1, to=99, width=5)
        self.player_no.grid(row=1, column=1, sticky="w")
        tk.Button(form, text="Add Event", command=self.add_event, bg=ACCENT
                  ).grid(row=0, column=2, rowspan=2, padx=6, sticky="ns")

        list_frame = tk.Frame(tab_events, bg=PANEL)
        list_frame.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(list_frame)
        scroll.pack(side="right", fill="y")
        self.log = tk.Listbox(list_frame, yscrollcommand=scroll.set, bg=DARK, fg="white",
                              font=("Consolas", 10), selectbackground=ACCENT,
                              selectforeground="black", activestyle="none")
        self.log.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.log.yview)
        self.log.bind("<Delete>", self.delete_selected_event)
        tk.Button(tab_events, text="Delete Selected Event", command=self.delete_selected_event
                  ).pack(fill="x", pady=(6, 0))

        self.stats_canvas = tk.Canvas(tab_stats, bg=DARK, highlightthickness=0)
        self.stats_canvas.pack(fill="both", expand=True)
        self.stats_canvas.bind("<Configure>", self.draw_stats)   # redraw when resized

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def typing(self):
        """True while the cursor is in a text box, so letters are not treated as shortcuts."""
        try:
            return isinstance(self.focus_get(), (tk.Entry, tk.Spinbox))
        except KeyError:
            return False

    def bind_keys(self):
        def guarded(action):
            return lambda event: None if self.typing() else action()

        self.bind("<space>", guarded(self.toggle_clock))
        self.bind("h", guarded(lambda: self.change_score("home", 1)))
        self.bind("a", guarded(lambda: self.change_score("away", 1)))
        self.bind("<Control-s>", lambda e: self.save_summary())
        self.bind("<Control-n>", lambda e: self.new_match())
        self.bind("<Control-h>", lambda e: self.open_history())
        self.bind("<F2>", lambda e: self.save_to_history())
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ------------------------------------------------------------------
    # Pitch drawing and players
    # ------------------------------------------------------------------
    def draw_pitch(self):
        c = self.canvas
        w, h, m = PITCH_W, PITCH_H, 14
        for i in range(8):
            shade = "#2e8b57" if i % 2 == 0 else "#2a8052"
            c.create_rectangle(i * w / 8, 0, (i + 1) * w / 8, h, fill=shade, outline=shade)
        c.create_rectangle(m, m, w - m, h - m, outline=LINE, width=2)
        c.create_line(w / 2, m, w / 2, h - m, fill=LINE, width=2)
        c.create_oval(w / 2 - 45, h / 2 - 45, w / 2 + 45, h / 2 + 45, outline=LINE, width=2)
        c.create_oval(w / 2 - 3, h / 2 - 3, w / 2 + 3, h / 2 + 3, fill=LINE, outline=LINE)
        for x0, x1 in ((m, m + 80), (w - m - 80, w - m)):
            c.create_rectangle(x0, h / 2 - 80, x1, h / 2 + 80, outline=LINE, width=2)
        for x0, x1 in ((m, m + 28), (w - m - 28, w - m)):
            c.create_rectangle(x0, h / 2 - 36, x1, h / 2 + 36, outline=LINE, width=2)

    def place_players(self):
        """(Re)create 11 home and 11 away markers using the chosen formations."""
        self.canvas.delete("player")
        for i, (fx, fy) in enumerate(FORMATIONS[self.home_form.get()], start=1):
            self.make_player(fx * PITCH_W, fy * PITCH_H, i, HOME_COL, "home")
        for i, (fx, fy) in enumerate(FORMATIONS[self.away_form.get()], start=1):
            self.make_player((1 - fx) * PITCH_W, fy * PITCH_H, i, AWAY_COL, "away")

    def on_formation(self, event=None):
        self.place_players()
        self.set_status(f"Formations: {self.home_name.get()} {self.home_form.get()}, "
                        f"{self.away_name.get()} {self.away_form.get()}")

    def make_player(self, x, y, number, colour, side):
        r = 13
        tags = ("player", side)
        self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=colour, outline="white", width=2, tags=tags)
        self.canvas.create_text(x, y, text=str(number), fill="white", font=("Segoe UI", 9, "bold"), tags=tags)

    # ---- drag and drop handlers ----
    def on_press(self, event):
        item = self.canvas.find_withtag("current")
        if not item:
            return
        self.drag_item = item[0]
        x1, y1, x2, y2 = self.canvas.bbox(self.drag_item)
        near = self.canvas.find_overlapping(x1, y1, x2, y2)
        # a player = an oval and a number that sit at the same position
        self.drag_group = [i for i in near if "player" in self.canvas.gettags(i)
                           and self.same_marker(i, self.drag_item)]
        self.last = (event.x, event.y)
        for i in self.drag_group:
            self.canvas.tag_raise(i)

    def same_marker(self, a, b):
        ax1, ay1, ax2, ay2 = self.canvas.bbox(a)
        bx1, by1, bx2, by2 = self.canvas.bbox(b)
        return (abs((ax1 + ax2) / 2 - (bx1 + bx2) / 2) < 8
                and abs((ay1 + ay2) / 2 - (by1 + by2) / 2) < 8)

    def on_drag(self, event):
        if not self.drag_item:
            return
        dx, dy = event.x - self.last[0], event.y - self.last[1]
        x1, y1, x2, y2 = self.canvas.bbox(self.drag_item)
        if x1 + dx < 0 or x2 + dx > PITCH_W or y1 + dy < 0 or y2 + dy > PITCH_H:
            return                                        # keep the marker inside the pitch
        for i in self.drag_group:
            self.canvas.move(i, dx, dy)
        self.last = (event.x, event.y)
        self.coord_lbl.config(text=f"Position: x={event.x}, y={event.y}")

    def on_release(self, event):
        if self.drag_item:
            self.set_status(f"Player moved to ({event.x}, {event.y})")
        self.drag_item = None

    # ------------------------------------------------------------------
    # Match data: everything is derived from self.events
    # ------------------------------------------------------------------
    def score(self, side):
        return sum(1 for e in self.events if e["team"] == side and e["kind"] == "Goal")

    def count(self, side, kind):
        return sum(1 for e in self.events if e["team"] == side and e["kind"] == kind)

    def change_score(self, side, delta):
        if delta > 0:
            self.events.append({"secs": self.seconds, "team": side, "kind": "Goal", "player": None})
            self.log.see("end")
        else:                                              # remove the most recent goal of that team
            for i in range(len(self.events) - 1, -1, -1):
                if self.events[i]["team"] == side and self.events[i]["kind"] == "Goal":
                    del self.events[i]
                    break
        self.refresh_all()

    def add_event(self):
        try:
            number = int(self.player_no.get())
            if not 1 <= number <= 99:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid player number", "Player # must be a whole number from 1 to 99.")
            return
        side = "home" if self.event_team.get() == "Home" else "away"
        self.events.append({"secs": self.seconds, "team": side,
                            "kind": self.event_type.get(), "player": number})
        self.refresh_all()
        self.log.see("end")
        self.set_status(f"{self.event_type.get()} recorded")

    def delete_selected_event(self, event=None):
        selection = self.log.curselection()
        if not selection:
            self.set_status("Select an event first")
            return
        del self.events[selection[0]]
        self.refresh_all()

    # ------------------------------------------------------------------
    # Refreshing the screen
    # ------------------------------------------------------------------
    def refresh_all(self):
        self.update_labels()
        self.refresh_log()
        self.draw_stats()

    def update_labels(self):
        self.home_lbl.config(text=str(self.score("home")))
        self.away_lbl.config(text=str(self.score("away")))
        mins, secs = divmod(self.seconds, 60)
        self.clock_lbl.config(text=f"{mins:02d}:{secs:02d}")

    def refresh_log(self):
        self.log.delete(0, "end")
        for e in self.events:
            self.log.insert("end", describe(e, self.home_name.get(), self.away_name.get()))

    def draw_stats(self, event=None):
        """Butterfly bar chart: home bars grow left, away bars grow right."""
        c = self.stats_canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 280), max(c.winfo_height(), 300)
        mid = w / 2
        c.create_text(10, 16, text=self.home_name.get(), anchor="w", fill=HOME_COL,
                      font=("Segoe UI", 11, "bold"))
        c.create_text(w - 10, 16, text=self.away_name.get(), anchor="e", fill=AWAY_COL,
                      font=("Segoe UI", 11, "bold"))
        rows = [("Goal", "Goals")] + [(kind, kind) for kind in EVENT_TYPES]
        top = 40
        row_h = min(40, (h - top - 10) / len(rows))
        biggest = max([1] + [self.count(side, kind) for side in ("home", "away") for kind, _ in rows])
        span = mid - 36
        for i, (kind, label) in enumerate(rows):
            y = top + i * row_h
            c.create_text(mid, y + 6, text=label, fill="white", font=("Segoe UI", 9))
            for side, sign, colour in (("home", -1, HOME_COL), ("away", 1, AWAY_COL)):
                n = self.count(side, kind)
                x_end = mid + sign * span * n / biggest
                if n:
                    c.create_rectangle(mid, y + 14, x_end, y + 26, fill=colour, outline="")
                c.create_text(x_end + sign * 9, y + 20, text=str(n), fill="white",
                              font=("Consolas", 10, "bold"))
        c.create_line(mid, top, mid, top + len(rows) * row_h, fill=LINE)

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------
    def toggle_clock(self):
        self.running = not self.running
        self.start_btn.config(text="Pause" if self.running else "Start")
        self.set_status("Clock running" if self.running else "Clock paused")
        if self.running:
            self.tick()
        elif self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None

    def tick(self):
        if self.running:
            self.seconds += 1
            self.update_labels()
            self.timer_job = self.after(1000, self.tick)

    def reset_clock(self):
        if self.timer_job:
            self.after_cancel(self.timer_job)
            self.timer_job = None
        self.running = False
        self.seconds = 0
        self.start_btn.config(text="Start")
        self.update_labels()
        self.set_status("Clock reset")

    # ------------------------------------------------------------------
    # File, history and menu actions
    # ------------------------------------------------------------------
    def summary_text(self):
        home, away = self.home_name.get(), self.away_name.get()
        lines = [
            "MATCHDAY MANAGER - MATCH SUMMARY",
            f"Generated: {datetime.now():%d %b %Y %H:%M}",
            "",
            f"{home} {self.score('home')} - {self.score('away')} {away}",
            f"Match time: {self.seconds // 60:02d}:{self.seconds % 60:02d}",
            f"Formations: {home} {self.home_form.get()}, {away} {self.away_form.get()}",
            "",
            "EVENTS",
        ]
        lines += [describe(e, home, away) for e in self.events] or ["(no events recorded)"]
        return "\n".join(lines)

    def write_summary(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.summary_text())

    def save_summary(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text file", "*.txt")],
                                            initialfile="match_summary.txt")
        if path:
            self.write_summary(path)
            self.set_status(f"Summary saved to {path}")
            messagebox.showinfo("Saved", "Match summary saved successfully.")

    def save_match_record(self):
        return self.db.save_match(self.home_name.get(), self.away_name.get(),
                                  self.score("home"), self.score("away"), self.seconds, self.events)

    def save_to_history(self):
        if not self.events and self.seconds == 0:
            messagebox.showwarning("Nothing to save", "Play some of the match first.")
            return
        match_id = self.save_match_record()
        self.set_status(f"Match #{match_id} saved to history")
        if self.history_win and self.history_win.winfo_exists():
            self.history_win.load()
        messagebox.showinfo("Saved", f"Match #{match_id} saved to history.")

    def open_history(self):
        if self.history_win and self.history_win.winfo_exists():
            self.history_win.load()
            self.history_win.lift()
        else:
            self.history_win = HistoryWindow(self, self.db)

    def reset_match(self):
        self.events.clear()
        self.reset_clock()
        self.place_players()
        self.refresh_all()

    def new_match(self):
        if messagebox.askyesno("New match", "Reset score, clock and events?"):
            self.reset_match()

    def show_shortcuts(self):
        messagebox.showinfo("Shortcuts",
                            "Space   Start / pause clock\n"
                            "H       Home goal\n"
                            "A       Away goal\n"
                            "Ctrl+S  Save text summary\n"
                            "F2      Save match to history\n"
                            "Ctrl+H  Open match history\n"
                            "Ctrl+N  New match\n"
                            "Delete  Remove selected event\n\n"
                            "(H, A and Space are ignored while you type in a text box)")

    def show_about(self):
        messagebox.showinfo("About", "MatchDay Manager\nBuilt with Python, Tkinter and SQLite.")

    def on_exit(self):
        if messagebox.askokcancel("Exit", "Close MatchDay Manager?"):
            self.destroy()

    def set_status(self, text):
        self.status.config(text=text)


if __name__ == "__main__":
    MatchDayManager().mainloop()
