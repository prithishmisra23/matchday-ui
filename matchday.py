"""
MatchDay Manager - a football match scoreboard and tactics board built with Tkinter.

Features
  * Scoreboard with editable team names and goal buttons
  * Match clock driven by Tk's after() scheduler
  * Pitch drawn on a Canvas with draggable player markers (mouse events)
  * Event log (goals, cards, substitutions) in a Listbox with a Scrollbar
  * Menu bar, keyboard shortcuts and message boxes
  * Save a match summary to a text file
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

# ---------- colours ----------
BG = "#0f2a1d"
PANEL = "#16382a"
PITCH = "#2e8b57"
LINE = "#f2f2f2"
HOME_COL = "#1e88e5"
AWAY_COL = "#e53935"
ACCENT = "#ffd54f"

PITCH_W, PITCH_H = 560, 360


class MatchDayManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MatchDay Manager")
        self.geometry("980x640")
        self.configure(bg=BG)
        self.minsize(900, 600)

        # ----- state -----
        self.home_score = 0
        self.away_score = 0
        self.seconds = 0
        self.running = False
        self.timer_job = None
        self.drag_item = None
        self.drag_offset = (0, 0)

        self.home_name = tk.StringVar(value="Home FC")
        self.away_name = tk.StringVar(value="Away United")
        self.event_type = tk.StringVar(value="Yellow Card")
        self.event_team = tk.StringVar(value="Home")

        self.build_menu()
        self.build_scoreboard()
        self.build_body()
        self.bind_keys()
        self.draw_pitch()
        self.place_players()
        self.update_labels()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Summary...", accelerator="Ctrl+S",
                              command=self.save_summary)
        file_menu.add_command(label="New Match", accelerator="Ctrl+N",
                              command=self.new_match)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=file_menu)

        match_menu = tk.Menu(menubar, tearoff=0)
        match_menu.add_command(label="Start / Pause", accelerator="Space",
                               command=self.toggle_clock)
        match_menu.add_command(label="Reset Player Positions",
                               command=self.place_players)
        menubar.add_cascade(label="Match", menu=match_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def build_scoreboard(self):
        board = tk.Frame(self, bg=PANEL, bd=0, highlightthickness=2,
                         highlightbackground=ACCENT)
        board.pack(fill="x", padx=14, pady=(14, 8))
        board.columnconfigure((0, 4), weight=1)

        # home side
        home = tk.Frame(board, bg=PANEL)
        home.grid(row=0, column=0, padx=10, pady=8)
        tk.Entry(home, textvariable=self.home_name, font=("Segoe UI", 14, "bold"),
                 justify="center", width=14, bg=HOME_COL, fg="white",
                 insertbackground="white", relief="flat").pack(pady=(0, 6))
        hb = tk.Frame(home, bg=PANEL)
        hb.pack()
        tk.Button(hb, text="-", width=3, command=lambda: self.change_score("home", -1)
                  ).pack(side="left", padx=2)
        tk.Button(hb, text="+ GOAL", width=9, bg=HOME_COL, fg="white",
                  command=lambda: self.change_score("home", 1)).pack(side="left", padx=2)

        # score
        self.home_lbl = tk.Label(board, text="0", font=("Consolas", 48, "bold"),
                                 bg=PANEL, fg="white", width=2)
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

        self.away_lbl = tk.Label(board, text="0", font=("Consolas", 48, "bold"),
                                 bg=PANEL, fg="white", width=2)
        self.away_lbl.grid(row=0, column=3)

        # away side
        away = tk.Frame(board, bg=PANEL)
        away.grid(row=0, column=4, padx=10, pady=8)
        tk.Entry(away, textvariable=self.away_name, font=("Segoe UI", 14, "bold"),
                 justify="center", width=14, bg=AWAY_COL, fg="white",
                 insertbackground="white", relief="flat").pack(pady=(0, 6))
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
        tk.Label(left, text="Tactics Board  -  drag the players", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        self.canvas = tk.Canvas(left, width=PITCH_W, height=PITCH_H, bg=PITCH,
                                highlightthickness=2, highlightbackground=LINE)
        self.canvas.pack()
        # mouse events for drag and drop
        self.canvas.tag_bind("player", "<ButtonPress-1>", self.on_press)
        self.canvas.tag_bind("player", "<B1-Motion>", self.on_drag)
        self.canvas.tag_bind("player", "<ButtonRelease-1>", self.on_release)
        self.canvas.tag_bind("player", "<Enter>", lambda e: self.canvas.config(cursor="hand2"))
        self.canvas.tag_bind("player", "<Leave>", lambda e: self.canvas.config(cursor=""))

        self.coord_lbl = tk.Label(left, text="Hover or drag a player", bg=BG, fg="white",
                                  font=("Segoe UI", 9))
        self.coord_lbl.pack(anchor="w", pady=(4, 0))

        # ---- events (right) ----
        right = tk.Frame(body, bg=PANEL, padx=10, pady=10)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        tk.Label(right, text="Match Events", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")

        form = tk.Frame(right, bg=PANEL)
        form.pack(fill="x", pady=6)
        ttk.Combobox(form, textvariable=self.event_team, values=["Home", "Away"],
                     state="readonly", width=7).grid(row=0, column=0, padx=2)
        ttk.Combobox(form, textvariable=self.event_type,
                     values=["Yellow Card", "Red Card", "Substitution", "Foul",
                             "Corner", "Offside", "Injury"],
                     state="readonly", width=13).grid(row=0, column=1, padx=2)
        tk.Label(form, text="Player #", bg=PANEL, fg="white").grid(row=1, column=0, pady=4)
        self.player_no = tk.Spinbox(form, from_=1, to=99, width=5)
        self.player_no.grid(row=1, column=1, sticky="w")
        tk.Button(form, text="Add Event", command=self.add_event, bg=ACCENT
                  ).grid(row=0, column=2, rowspan=2, padx=6, sticky="ns")

        list_frame = tk.Frame(right, bg=PANEL)
        list_frame.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(list_frame)
        scroll.pack(side="right", fill="y")
        self.log = tk.Listbox(list_frame, yscrollcommand=scroll.set, bg="#0b1f15",
                              fg="white", font=("Consolas", 10), selectbackground=ACCENT,
                              selectforeground="black", activestyle="none")
        self.log.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.log.yview)
        self.log.bind("<Delete>", self.delete_selected_event)

        tk.Button(right, text="Delete Selected Event", command=self.delete_selected_event
                  ).pack(fill="x", pady=(6, 0))

    def bind_keys(self):
        self.bind("<space>", lambda e: self.toggle_clock())
        self.bind("h", lambda e: self.change_score("home", 1))
        self.bind("a", lambda e: self.change_score("away", 1))
        self.bind("<Control-s>", lambda e: self.save_summary())
        self.bind("<Control-n>", lambda e: self.new_match())
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ------------------------------------------------------------------
    # Pitch drawing and players
    # ------------------------------------------------------------------
    def draw_pitch(self):
        c = self.canvas
        w, h, m = PITCH_W, PITCH_H, 14
        # grass stripes
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
        """(Re)create 11 home and 11 away markers in a 4-4-2 style formation."""
        self.canvas.delete("player")
        w, h = PITCH_W, PITCH_H
        formation = [(0.06, 0.5)] + \
                    [(0.20, y) for y in (0.15, 0.38, 0.62, 0.85)] + \
                    [(0.36, y) for y in (0.15, 0.38, 0.62, 0.85)] + \
                    [(0.46, y) for y in (0.35, 0.65)]
        for i, (fx, fy) in enumerate(formation, start=1):
            self.make_player(fx * w, fy * h, i, HOME_COL, "home")
            self.make_player((1 - fx) * w, fy * h, i, AWAY_COL, "away")

    def make_player(self, x, y, number, colour, side):
        r = 13
        tags = ("player", side)
        self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=colour,
                                outline="white", width=2, tags=tags)
        self.canvas.create_text(x, y, text=str(number), fill="white",
                                font=("Segoe UI", 9, "bold"), tags=tags)

    # ---- drag and drop handlers ----
    def on_press(self, event):
        item = self.canvas.find_withtag("current")
        if not item:
            return
        self.drag_item = item[0]
        # find the oval/text pair that belongs together via their shared position
        x1, y1, x2, y2 = self.canvas.bbox(self.drag_item)
        self.drag_group = self.canvas.find_overlapping(x1, y1, x2, y2)
        self.drag_group = [i for i in self.drag_group if "player" in self.canvas.gettags(i)
                           and self.same_marker(i, self.drag_item)]
        self.last = (event.x, event.y)
        for i in self.drag_group:
            self.canvas.tag_raise(i)

    def same_marker(self, a, b):
        ax1, ay1, ax2, ay2 = self.canvas.bbox(a)
        bx1, by1, bx2, by2 = self.canvas.bbox(b)
        return abs((ax1 + ax2) / 2 - (bx1 + bx2) / 2) < 8 and abs((ay1 + ay2) / 2 - (by1 + by2) / 2) < 8

    def on_drag(self, event):
        if not self.drag_item:
            return
        dx, dy = event.x - self.last[0], event.y - self.last[1]
        # keep the marker inside the pitch
        x1, y1, x2, y2 = self.canvas.bbox(self.drag_item)
        if x1 + dx < 0 or x2 + dx > PITCH_W or y1 + dy < 0 or y2 + dy > PITCH_H:
            return
        for i in self.drag_group:
            self.canvas.move(i, dx, dy)
        self.last = (event.x, event.y)
        self.coord_lbl.config(text=f"Position: x={event.x}, y={event.y}")

    def on_release(self, event):
        if self.drag_item:
            self.set_status(f"Player moved to ({event.x}, {event.y})")
        self.drag_item = None

    # ------------------------------------------------------------------
    # Scoreboard / clock logic
    # ------------------------------------------------------------------
    def change_score(self, side, delta):
        if side == "home":
            self.home_score = max(0, self.home_score + delta)
            name = self.home_name.get()
        else:
            self.away_score = max(0, self.away_score + delta)
            name = self.away_name.get()
        if delta > 0:
            self.log_event(f"GOAL! {name}")
        self.update_labels()

    def update_labels(self):
        self.home_lbl.config(text=str(self.home_score))
        self.away_lbl.config(text=str(self.away_score))
        mins, secs = divmod(self.seconds, 60)
        self.clock_lbl.config(text=f"{mins:02d}:{secs:02d}")

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
    # Event log
    # ------------------------------------------------------------------
    def minute_stamp(self):
        return f"{self.seconds // 60:02d}'"

    def log_event(self, text):
        self.log.insert("end", f"{self.minute_stamp()}  {text}")
        self.log.yview_moveto(1)

    def add_event(self):
        team = self.home_name.get() if self.event_team.get() == "Home" else self.away_name.get()
        try:
            number = int(self.player_no.get())
        except ValueError:
            messagebox.showerror("Invalid player number", "Player # must be a whole number.")
            return
        self.log_event(f"{self.event_type.get()} - {team} #{number}")
        self.set_status(f"{self.event_type.get()} recorded")

    def delete_selected_event(self, event=None):
        sel = self.log.curselection()
        if not sel:
            self.set_status("Select an event first")
            return
        self.log.delete(sel[0])

    # ------------------------------------------------------------------
    # File / menu actions
    # ------------------------------------------------------------------
    def summary_text(self):
        lines = [
            "MATCHDAY MANAGER - MATCH SUMMARY",
            f"Generated: {datetime.now():%d %b %Y %H:%M}",
            "",
            f"{self.home_name.get()} {self.home_score} - {self.away_score} {self.away_name.get()}",
            f"Match time: {self.seconds // 60:02d}:{self.seconds % 60:02d}",
            "",
            "EVENTS",
        ]
        lines += list(self.log.get(0, "end")) or ["(no events recorded)"]
        return "\n".join(lines)

    def write_summary(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.summary_text())

    def save_summary(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text file", "*.txt")],
                                            initialfile="match_summary.txt")
        if path:
            self.write_summary(path)
            self.set_status(f"Summary saved to {path}")
            messagebox.showinfo("Saved", "Match summary saved successfully.")

    def new_match(self):
        if messagebox.askyesno("New match", "Reset score, clock and events?"):
            self.home_score = self.away_score = 0
            self.log.delete(0, "end")
            self.reset_clock()
            self.place_players()
            self.update_labels()

    def show_shortcuts(self):
        messagebox.showinfo("Shortcuts",
                            "Space   Start / pause clock\n"
                            "H       Home goal\n"
                            "A       Away goal\n"
                            "Ctrl+S  Save summary\n"
                            "Ctrl+N  New match\n"
                            "Delete  Remove selected event")

    def show_about(self):
        messagebox.showinfo("About", "MatchDay Manager\nBuilt with Python and Tkinter.")

    def on_exit(self):
        if messagebox.askokcancel("Exit", "Close MatchDay Manager?"):
            self.destroy()

    def set_status(self, text):
        self.status.config(text=text)


if __name__ == "__main__":
    MatchDayManager().mainloop()
