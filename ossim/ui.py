import os
import subprocess
import sys

try:
    import tkinter
    from tkinter import filedialog, messagebox, simpledialog
except ImportError:
    sys.stderr.write(
        "Python is missing Tk support (the tkinter module).\n"
        "Install it with your package manager, then retry:\n"
        "  Arch:    sudo pacman -S tk\n"
        "  Debian:  sudo apt install python3-tk\n"
        "  Fedora:  sudo dnf install python3-tkinter\n"
        "  macOS:   usually already present with python.org or Homebrew Python\n"
    )
    raise SystemExit(1)

from ossim import (
    SimConfig,
    parse_file,
    parse_text,
    simulate,
    simulate_all,
)
from ossim.cli import (
    ALGORITHM_NOTES,
    ORDER,
    algorithm_help,
    display_name,
    general_help,
)
from ossim.parser import ParseError
from ossim.report import (
    comparison_table,
    format_metrics,
    format_report,
    render_gantt,
    table,
    to_csv,
    to_dict,
    to_json,
)

_CTK_SPEC = "customtkinter>=5.2.2"


def _pip_install(spec):
    attempts = [
        [sys.executable, "-m", "pip", "install", "--user", spec],
        [sys.executable, "-m", "pip", "install", spec],
        [sys.executable, "-m", "pip", "install", "--user", "--break-system-packages", spec],
    ]
    for cmd in attempts:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.returncode == 0:
            return True
    return False


def _ensure_customtkinter():
    try:
        import customtkinter  # noqa: F401
        return
    except ImportError:
        pass
    print(f"GUI dependency missing; installing {_CTK_SPEC} ...", flush=True)
    if not _pip_install(_CTK_SPEC):
        sys.stderr.write(
            "Could not install customtkinter automatically.\n"
            "Install the project (no virtual environment needed):\n"
            f"  {sys.executable} -m pip install --user .\n"
            "or just:\n"
            f"  {sys.executable} -m pip install --user {_CTK_SPEC}\n"
        )
        raise SystemExit(1)
    import importlib
    importlib.invalidate_caches()
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "customtkinter was installed, but this Python still cannot import it.\n"
            "Open a new terminal, or run:\n"
            f"  {sys.executable} -m pip show customtkinter\n"
        )
        raise SystemExit(1)


_ensure_customtkinter()
import customtkinter as ctk  # noqa: E402

# Set appearance mode and color theme
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# Theme colors for popups and menus
_DROPDOWN_BG = ("#F4F4F4", "#2B2B2B")
_DROPDOWN_TEXT = ("#111111", "#F2F2F2")
_DROPDOWN_HOVER = ("#3B8ED0", "#1F6AA5")
_DROPDOWN_BORDER = ("#C4C4C4", "#5A5A5A")


class VisibleOptionMenu(ctk.CTkOptionMenu):
    """Option menu that opens an opaque popup list instead of a native Tk menu."""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("dropdown_fg_color", _DROPDOWN_BG)
        kwargs.setdefault("dropdown_text_color", _DROPDOWN_TEXT)
        kwargs.setdefault("dropdown_hover_color", _DROPDOWN_HOVER)
        super().__init__(master, **kwargs)
        self._popup = None
        self._ignore_next_click = False

    def _close_popup(self, _event=None):
        if self._popup is None:
            return
        popup = self._popup
        self._popup = None
        self._ignore_next_click = True
        self.after(200, self._clear_ignore_click)
        try:
            popup.destroy()
        except tkinter.TclError:
            pass

    def _clear_ignore_click(self):
        self._ignore_next_click = False

    def _close_if_pointer_left(self, _event=None):
        self.after(80, self._close_if_idle)

    def _close_if_idle(self):
        if self._popup is None:
            return
        try:
            x, y = self._popup.winfo_pointerxy()
            if self._popup.winfo_containing(x, y) is not None:
                return
        except tkinter.TclError:
            pass
        self._close_popup()

    def _clicked(self, event=0):
        if self._state == tkinter.DISABLED or not self._values:
            return
        if self._ignore_next_click:
            self._ignore_next_click = False
            return
        if self._popup is not None:
            self._close_popup()
        else:
            self._open_dropdown_menu()

    def _open_dropdown_menu(self):
        self._close_popup()

        popup = ctk.CTkToplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        try:
            popup.attributes("-alpha", 1.0)
        except tkinter.TclError:
            pass
        popup.configure(fg_color=_DROPDOWN_BG)

        frame = ctk.CTkFrame(
            popup,
            fg_color=_DROPDOWN_BG,
            border_width=1,
            border_color=_DROPDOWN_BORDER,
            corner_radius=6,
        )
        frame.pack(fill="both", expand=True)

        current = self._current_value
        for value in self._values:
            selected = value == current
            ctk.CTkButton(
                frame,
                text=value,
                anchor="w",
                height=28,
                corner_radius=4,
                fg_color=_DROPDOWN_HOVER if selected else "transparent",
                hover_color=_DROPDOWN_HOVER,
                text_color="#FFFFFF" if selected else _DROPDOWN_TEXT,
                command=lambda v=value: self._choose_value(v),
            ).pack(fill="x", padx=4, pady=2)

        popup.update_idletasks()
        width = max(self.winfo_width(), 160)
        height = frame.winfo_reqheight()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()

        # If popup goes below screen bottom, open above the menu
        screen_height = self.winfo_screenheight()
        if y + height > screen_height - 20:
            y = max(10, self.winfo_rooty() - height)

        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()
        popup.lift()
        popup.focus_set()
        popup.bind("<Escape>", self._close_popup)
        popup.bind("<FocusOut>", self._close_if_pointer_left)
        self._popup = popup

    def _choose_value(self, value):
        self._close_popup()
        self._dropdown_callback(value)


DEFAULT_STARTER_WORKLOAD = """# Starter Workload Definition
# Format:
#   resources R1=2, R2=1              # optional instance counts
#   program <Name> priority=1 arrival=0
#       cpu(4)                        # CPU burst
#       io(2)                         # I/O wait
#       resource(1, allocate)         # acquire resource
#       resource(1, release)          # release resource
#       end

program P1 priority=1 arrival=0
    cpu(2)
    resource(1, allocate)
    cpu(2)
    resource(1, release)
    end

program P2 priority=2 arrival=1
    cpu(3)
    resource(1, allocate)
    cpu(1)
    resource(1, release)
    end
"""

WORKLOAD_SYNTAX_GUIDE = """================================================================================
                    WORKLOAD SYNTAX & WRITING GUIDE
================================================================================

A workload file describes the processes and resources to be simulated by the OS kernel.
The file format is plain text, case-insensitive, and ignores blank lines and comments (#).

--------------------------------------------------------------------------------
1. GLOBAL RESOURCE DECLARATIONS (Optional)
--------------------------------------------------------------------------------
By default, every resource referenced in the file exists with a capacity of 1 instance.
To configure multiple instances of a resource (e.g. 2 printers, 3 tape drives), declare
them at the top of the file:

    resources R1=2, R2=3, R3=1

• Resource names can be written as R1, r1, or bare numbers 1, 2, or names like tape=2.
• If omitted, any resource requested defaults to 1 instance.


--------------------------------------------------------------------------------
2. PROCESS DEFINITIONS
--------------------------------------------------------------------------------
Each process begins with the 'program' header and terminates with 'end'.

Syntax:
    program <Name> [priority=INTEGER] [arrival=FLOAT]

Attributes (all optional, default to priority=0 and arrival=0):
  • priority / prio / p : Process priority number.
                          LOWER number = HIGHER priority (0 is highest).
                          Used by Priority and Priority-Preemptive schedulers.
  • arrival / arrive / at : Virtual time when the process enters the Ready Queue.
                          Can be 0, 1, 2.5, etc.

Examples:
    program Worker
    program DatabaseServer priority=1 arrival=0
    program BackgroundBackup priority=10 arrival=5


--------------------------------------------------------------------------------
3. INSTRUCTIONS (Inside a program ... end block)
--------------------------------------------------------------------------------
Every command runs sequentially within the process.

1) CPU Bursts
   • cpu(N)       : Execute on CPU for N time units.
   • wait(N)      : (Alias) Burn N units of CPU.
   • compute(N)   : (Alias) Burn N units of CPU.
   Example:
       cpu(4)     # Uses the CPU for 4 units of time

2) I/O Operations
   • io(N)        : Process blocks off the CPU for N units of time (simulating disk/net).
   • sleep(N)     : (Alias) Sleep for N units.
   Example:
       io(2)      # CPU yields to next process; this process returns to ready queue after 2 units

3) Resource Allocation (Locking)
   • resource(R, allocate)  : Request 1 instance of resource R.
   • acquire(R)             : (Alias) Lock/acquire resource R.
   • lock(R)                : (Alias) Lock resource R.
   If resource is available, it is acquired immediately.
   If busy, process is blocked until it becomes available (or triggers deadlock).
   Example:
       resource(1, allocate)
       acquire(2)

4) Resource Release (Unlocking)
   • resource(R, release)   : Release 1 instance of resource R.
   • release(R)             : (Alias) Free resource R.
   • unlock(R)              : (Alias) Unlock resource R.
   Example:
       resource(1, release)
       release(2)

5) Process End
   • end          : Marks the completion of the process.
                    Any resources still held are automatically released by the kernel.


--------------------------------------------------------------------------------
4. COMPLETE WORKED EXAMPLES
--------------------------------------------------------------------------------

[Example A: CPU-Bound Workload (Batch Processing)]
Testing FCFS, SJF, SRTF, and Round Robin:

    program JobA arrival=0
        cpu(6)
        end

    program JobB arrival=1
        cpu(2)
        end

    program JobC arrival=2
        cpu(4)
        end

• Under FCFS : JobA runs 0->6, then JobB runs 6->8, then JobC runs 8->12.
• Under SJF  : JobA starts at 0; when it finishes at 6, JobB runs first (burst 2), then JobC.
• Under SRTF : When JobB arrives at t=1, its remaining time (2) is less than JobA's remaining (5),
               so JobB preempts JobA immediately!
• Under RR   : Processes take turns in slices of quantum length (e.g. -q 2).


[Example B: Interactive I/O Cycle]
Processes that alternate between computation and I/O:

    program WebRequest priority=1 arrival=0
        cpu(1)                  # parse HTTP request
        io(3)                   # wait for database query
        cpu(2)                  # render HTML template
        end

    program BackgroundJob priority=2 arrival=0
        cpu(8)                  # runs on CPU while WebRequest is blocked on I/O
        end


[Example C: Deadlock Scenario (Circular Wait)]
Processes fighting over two shared mutexes (R1 and R2):

    program Thread1 arrival=0
        resource(1, allocate)  # acquires R1
        io(1)
        resource(2, allocate)  # wants R2 (held by Thread2) -> BLOCKS
        cpu(1)
        end

    program Thread2 arrival=0
        resource(2, allocate)  # acquires R2
        io(1)
        resource(1, allocate)  # wants R1 (held by Thread1) -> BLOCKS
        cpu(1)
        end

• At t=1, both threads block waiting for each other -> Deadlock detected!
• The simulator will apply your chosen policy (Terminate, Preempt, or Manual prompt).
• Or, enable Banker's avoidance (--avoidance banker) to prevent the unsafe allocation!


--------------------------------------------------------------------------------
5. COMMON MISTAKES & ERROR PREVENTION
--------------------------------------------------------------------------------
1) Missing 'end':
   Each 'program' block MUST conclude with an 'end' line.

2) Releasing unheld resources:
   Calling resource(1, release) without an earlier allocate causes a warning.

3) Duplicate Process Names:
   Process names must be unique within the same workload (e.g. P1, P2, P3).

4) Process with no instructions:
   A process must have at least one instruction (e.g. cpu(1)) before 'end'.

5) Deadlocks without recovery:
   If your workload deadlocks and recovery is set to terminate, the victim process
   will be terminated based on your victim policy (resources, priority, or progress).
================================================================================
"""


class SimulatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("CLI OS Simulator - Interactive GUI")
        self.geometry("1200x780")
        self.minsize(980, 640)

        # Track file and simulation state
        self.current_filepath = None
        self.last_sim = None
        self.last_algo = "fcfs"
        self.last_source = "workload"
        self.last_comparison = None  # (runs, sims, names)
        self.is_comparison_mode = False
        self._last_deadlock_info = ""
        self._suppress_status_update = False

        # Configure layout (Sidebar + Main content)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Build UI components
        self._build_sidebar()
        self._build_main_content()

        # Load initial file (program.txt if present)
        self._load_initial_workload()

        # Trigger algorithm selection update
        self._on_algo_changed("fcfs - First-Come, First-Served")

    # ------------------------------------------------------------------ #
    # Sidebar
    # ------------------------------------------------------------------ #
    def _build_sidebar(self):
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=280, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")

        # Title
        self.title_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="OS SIMULATOR",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.title_label.pack(padx=16, pady=(16, 2), anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="CPU Scheduling & Deadlock Engine",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.subtitle_label.pack(padx=16, pady=(0, 14), anchor="w")

        # --- SECTION: Workload ---
        self._create_section_header("Workload File")

        self.file_status_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="program.txt",
            font=ctk.CTkFont(size=12, weight="bold"),
            wraplength=250,
            anchor="w",
        )
        self.file_status_label.pack(padx=16, pady=(2, 6), fill="x")

        file_btn_row = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        file_btn_row.pack(padx=16, pady=(0, 6), fill="x")

        self.browse_btn = ctk.CTkButton(
            file_btn_row,
            text="Browse...",
            width=110,
            height=28,
            command=self.browse_file,
        )
        self.browse_btn.pack(side="left", padx=(0, 6))

        # Quick Example Loader
        self.example_var = ctk.StringVar(value="Load Example...")
        self.example_options = [
            "Load Example...",
            "program.txt (Default)",
            "examples/timesharing.txt",
            "examples/deadlock.txt",
            "examples/banker.txt",
        ]
        self.example_menu = VisibleOptionMenu(
            self.sidebar_frame,
            values=self.example_options,
            variable=self.example_var,
            command=self._on_example_selected,
            width=248,
            height=28,
        )
        self.example_menu.pack(padx=16, pady=(0, 14), fill="x")

        # --- SECTION: Scheduling Policy ---
        self._create_section_header("Scheduling Policy")

        self.algo_label = ctk.CTkLabel(self.sidebar_frame, text="Algorithm:", font=ctk.CTkFont(size=12))
        self.algo_label.pack(padx=16, pady=(2, 2), anchor="w")

        self.algo_display_map = {
            "fcfs": "fcfs - First-Come, First-Served",
            "sjf": "sjf - Shortest Job First",
            "srtf": "srtf - Shortest Remaining Time First",
            "rr": "rr - Round Robin",
            "priority": "priority - Priority (non-preemptive)",
            "priority-p": "priority-p - Priority (preemptive)",
            "hrrn": "hrrn - Highest Response Ratio Next",
        }
        self.algo_var = ctk.StringVar(value=self.algo_display_map["fcfs"])
        self.algo_menu = VisibleOptionMenu(
            self.sidebar_frame,
            values=list(self.algo_display_map.values()),
            variable=self.algo_var,
            command=self._on_algo_changed,
            width=248,
            height=28,
        )
        self.algo_menu.pack(padx=16, pady=(0, 8), fill="x")

        # Quantum
        self.quantum_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Round Robin Quantum (-q):",
            font=ctk.CTkFont(size=12),
        )
        self.quantum_label.pack(padx=16, pady=(2, 2), anchor="w")

        self.quantum_var = ctk.StringVar(value="4")
        self.quantum_entry = ctk.CTkEntry(
            self.sidebar_frame,
            textvariable=self.quantum_var,
            width=248,
            height=28,
        )
        self.quantum_entry.pack(padx=16, pady=(0, 14), fill="x")

        # --- SECTION: Deadlock Management ---
        self._create_section_header("Deadlock Management")

        # Avoidance Mode
        self.avoidance_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Avoidance Mode (--avoidance):",
            font=ctk.CTkFont(size=12),
        )
        self.avoidance_label.pack(padx=16, pady=(2, 2), anchor="w")

        self.avoidance_map = {
            "none - Disabled (Detection only)": "none",
            "banker - Banker's Algorithm": "banker",
        }
        self.avoidance_var = ctk.StringVar(value="none - Disabled (Detection only)")
        self.avoidance_menu = VisibleOptionMenu(
            self.sidebar_frame,
            values=list(self.avoidance_map.keys()),
            variable=self.avoidance_var,
            width=248,
            height=28,
        )
        self.avoidance_menu.pack(padx=16, pady=(0, 8), fill="x")

        # Recovery Policy
        self.recovery_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Recovery Policy (--deadlock):",
            font=ctk.CTkFont(size=12),
        )
        self.recovery_label.pack(padx=16, pady=(2, 2), anchor="w")

        self.recovery_map = {
            "terminate - Terminate victim": "terminate",
            "preempt - Preempt resources": "preempt",
            "manual - Manual interactive": "manual",
        }
        self.recovery_var = ctk.StringVar(value="terminate - Terminate victim")
        self.recovery_menu = VisibleOptionMenu(
            self.sidebar_frame,
            values=list(self.recovery_map.keys()),
            variable=self.recovery_var,
            width=248,
            height=28,
        )
        self.recovery_menu.pack(padx=16, pady=(0, 8), fill="x")

        # Victim Selection Policy
        self.victim_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Victim Selection (--victim):",
            font=ctk.CTkFont(size=12),
        )
        self.victim_label.pack(padx=16, pady=(2, 2), anchor="w")

        self.victim_map = {
            "resources - Most resources held": "resources",
            "priority - Lowest priority process": "priority",
            "progress - Least progress made": "progress",
        }
        self.victim_var = ctk.StringVar(value="resources - Most resources held")
        self.victim_menu = VisibleOptionMenu(
            self.sidebar_frame,
            values=list(self.victim_map.keys()),
            variable=self.victim_var,
            width=248,
            height=28,
        )
        self.victim_menu.pack(padx=16, pady=(0, 14), fill="x")

        # --- SECTION: Execution Actions ---
        self._create_section_header("Run & Export")

        # Run Button
        self.run_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="▶ Run Simulation",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=34,
            fg_color=("#2FA572", "#228B55"),
            hover_color=("#26855B", "#1C7446"),
            command=self.run_simulation,
        )
        self.run_btn.pack(padx=16, pady=(4, 6), fill="x")

        # Compare All Button
        self.compare_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="⚡ Compare All Algorithms (--all)",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            fg_color=("#6552B5", "#513F9D"),
            hover_color=("#5543A0", "#423287"),
            command=self.run_compare_all,
        )
        self.compare_btn.pack(padx=16, pady=(0, 6), fill="x")

        # Export Report Button
        self.export_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="💾 Export Report...",
            font=ctk.CTkFont(size=12),
            height=30,
            fg_color="transparent",
            border_width=1,
            command=self.export_report,
        )
        self.export_btn.pack(padx=16, pady=(0, 14), fill="x")

        # --- SECTION: Appearance ---
        self._create_section_header("Preferences")

        self.theme_label = ctk.CTkLabel(self.sidebar_frame, text="Appearance Mode:", font=ctk.CTkFont(size=11))
        self.theme_label.pack(padx=16, pady=(2, 2), anchor="w")

        self.theme_menu = VisibleOptionMenu(
            self.sidebar_frame,
            values=["System", "Dark", "Light"],
            command=self._change_appearance_mode,
            width=248,
            height=26,
        )
        self.theme_menu.pack(padx=16, pady=(0, 16), fill="x")

    def _create_section_header(self, title: str):
        label = ctk.CTkLabel(
            self.sidebar_frame,
            text=title.upper(),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#4A7CB5", "#6AA8E8"),
        )
        label.pack(padx=16, pady=(8, 2), anchor="w")

    # ------------------------------------------------------------------ #
    # Main Content Area (Tabs)
    # ------------------------------------------------------------------ #
    def _build_main_content(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=(12, 16), pady=12, sticky="nsew")

        self.tabview.add("📝 Editor")
        self.tabview.add("📊 Metrics")
        self.tabview.add("📈 Comparison")
        self.tabview.add("📋 Process Table")
        self.tabview.add("⏱ Timeline")
        self.tabview.add("📜 Logs")
        self.tabview.add("❓ Help & Guide")

        self._build_editor_tab()
        self._build_metrics_tab()
        self._build_comparison_tab()
        self._build_process_tab()
        self._build_timeline_tab()
        self._build_logs_tab()
        self._build_help_tab()

    def _build_editor_tab(self):
        tab = self.tabview.tab("📝 Editor")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Editor Toolbar
        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=4, pady=(2, 6), sticky="ew")

        ctk.CTkButton(
            toolbar,
            text="📄 New",
            width=65,
            height=28,
            command=self.new_file,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            toolbar,
            text="📂 Open...",
            width=75,
            height=28,
            command=self.browse_file,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            toolbar,
            text="💾 Save",
            width=65,
            height=28,
            command=self.save_file,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            toolbar,
            text="💾 Save As...",
            width=85,
            height=28,
            command=self.save_file_as,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            toolbar,
            text="🔍 Validate Syntax",
            width=115,
            height=28,
            command=self.validate_workload_syntax,
        ).pack(side="left", padx=(10, 2))

        # Quick Syntax Writing Guide Shortcut
        ctk.CTkButton(
            toolbar,
            text="📖 Syntax Guide",
            width=105,
            height=28,
            fg_color=("#3B8ED0", "#1F6AA5"),
            hover_color=("#337AB7", "#19578A"),
            command=self.open_syntax_guide,
        ).pack(side="left", padx=4)

        self.editor_status = ctk.CTkLabel(
            toolbar,
            text="Ready. Edits here are simulated immediately.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.editor_status.pack(side="right", padx=6)

        # Editor Container (Line Numbers Gutter + Editor Textbox)
        editor_container = ctk.CTkFrame(tab, fg_color="transparent")
        editor_container.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        editor_container.grid_columnconfigure(1, weight=1)
        editor_container.grid_rowconfigure(0, weight=1)

        mono_font = ctk.CTkFont(family="Courier", size=13)

        # Line numbers gutter
        self.line_numbers_text = ctk.CTkTextbox(
            editor_container,
            width=48,
            font=mono_font,
            wrap="none",
            activate_scrollbars=False,
            fg_color=("gray88", "gray18"),
            text_color=("gray45", "gray60"),
            corner_radius=4,
        )
        self.line_numbers_text.grid(row=0, column=0, sticky="ns", padx=(0, 2))
        self.line_numbers_text.configure(state="disabled")

        # Main text editor
        self.editor_text = ctk.CTkTextbox(
            editor_container,
            font=mono_font,
            wrap="none",
            undo=True,
            corner_radius=4,
        )
        self.editor_text.grid(row=0, column=1, sticky="nsew")

        # Synchronize scrollbars between main editor and line numbers gutter
        def _on_text_scroll(*args):
            self.editor_text._y_scrollbar.set(*args)
            try:
                self.line_numbers_text._textbox.yview_moveto(args[0])
            except Exception:
                pass

        def _on_scrollbar_drag(*args):
            try:
                self.editor_text._textbox.yview(*args)
                self.line_numbers_text._textbox.yview(*args)
            except Exception:
                pass

        self.editor_text._textbox.configure(yscrollcommand=_on_text_scroll)
        self.editor_text._y_scrollbar.configure(command=_on_scrollbar_drag)

        # Forward mouse wheel events from line numbers gutter to main editor
        def _on_gutter_scroll(event):
            try:
                if event.num == 5 or getattr(event, "delta", 0) < 0:
                    self.editor_text._textbox.yview_scroll(2, "units")
                elif event.num == 4 or getattr(event, "delta", 0) > 0:
                    self.editor_text._textbox.yview_scroll(-2, "units")
            except Exception:
                pass
            return "break"

        self.line_numbers_text._textbox.bind("<Button-4>", _on_gutter_scroll)
        self.line_numbers_text._textbox.bind("<Button-5>", _on_gutter_scroll)
        self.line_numbers_text._textbox.bind("<MouseWheel>", _on_gutter_scroll)

        # Update line numbers on keyboard input, paste, and text modifications
        self.editor_text.bind("<KeyRelease>", self._update_line_numbers)
        self.editor_text.bind("<ButtonRelease>", self._update_line_numbers)
        self.editor_text.bind("<<Modified>>", self._on_text_modified)

    def _on_text_modified(self, event=None):
        try:
            flag = self.editor_text._textbox.edit_modified()
            if flag:
                self._update_line_numbers()
                self.editor_text._textbox.edit_modified(False)
        except Exception:
            pass

    def _update_line_numbers(self, event=None):
        try:
            total_lines = int(self.editor_text._textbox.index("end - 1 chars").split(".")[0])
            if total_lines < 1:
                total_lines = 1
            line_str = "\n".join(f"{i:>3} " if total_lines < 1000 else f"{i:>4} " for i in range(1, total_lines + 1))
            self.line_numbers_text.configure(state="normal")
            self.line_numbers_text.delete("1.0", "end")
            self.line_numbers_text.insert("1.0", line_str)
            self.line_numbers_text.configure(state="disabled")

            # Synchronize y-view
            yview = self.editor_text._textbox.yview()
            if yview:
                self.line_numbers_text._textbox.yview_moveto(yview[0])

            # Adjust width if line count expands to 4 or more digits
            digits = len(str(total_lines))
            needed_width = max(45, (digits + 2) * 9)
            self.line_numbers_text.configure(width=needed_width)

            if not self._suppress_status_update:
                self.editor_status.configure(text=f"Lines: {total_lines} | Ready")
        except Exception:
            pass

    def open_syntax_guide(self):
        """Switch directly to the Help & Guide tab and display the Syntax Guide."""
        self.tabview.set("❓ Help & Guide")
        self.help_topic_var.set("📝 Workload Syntax Writing Guide (Detailed)")
        self._update_help_text("syntax")

    def _build_metrics_tab(self):
        tab = self.tabview.tab("📊 Metrics")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.metrics_text = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Courier", size=13),
            wrap="none",
        )
        self.metrics_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.metrics_text.insert(
            ctk.END,
            "Run a simulation (or click '▶ Run Simulation' on the left) to view aggregate metrics here.\n",
        )

    def _build_comparison_tab(self):
        tab = self.tabview.tab("📈 Comparison")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.comparison_text = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Courier", size=13),
            wrap="none",
        )
        self.comparison_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.comparison_text.insert(
            ctk.END,
            "Click '⚡ Compare All Algorithms (--all)' in the sidebar to run every scheduling\n"
            "algorithm on this workload and view the side-by-side comparative table.\n",
        )

    def _build_process_tab(self):
        tab = self.tabview.tab("📋 Process Table")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.process_text = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Courier", size=13),
            wrap="none",
        )
        self.process_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.process_text.insert(ctk.END, "Per-process metrics table will appear here.\n")

    def _build_timeline_tab(self):
        tab = self.tabview.tab("⏱ Timeline")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.timeline_text = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Courier", size=13),
            wrap="none",
        )
        self.timeline_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.timeline_text.insert(ctk.END, "Proportional ASCII Gantt timeline will appear here.\n")

    def _build_logs_tab(self):
        tab = self.tabview.tab("📜 Logs")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.logs_text = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Courier", size=13),
            wrap="none",
        )
        self.logs_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.logs_text.insert(ctk.END, "Step-by-step event trace log will appear here.\n")

    def _build_help_tab(self):
        tab = self.tabview.tab("❓ Help & Guide")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        help_top_row = ctk.CTkFrame(tab, fg_color="transparent")
        help_top_row.grid(row=0, column=0, padx=4, pady=(2, 6), sticky="ew")

        ctk.CTkLabel(
            help_top_row,
            text="Documentation Topic:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=4)

        self.help_topics_map = {
            "General Overview & Guide": "overview",
            "📝 Workload Syntax Writing Guide (Detailed)": "syntax",
            "fcfs - First-Come, First-Served": "fcfs",
            "sjf - Shortest Job First": "sjf",
            "srtf - Shortest Remaining Time First": "srtf",
            "rr - Round Robin": "rr",
            "priority - Priority (non-preemptive)": "priority",
            "priority-p - Priority (preemptive)": "priority-p",
            "hrrn - Highest Response Ratio Next": "hrrn",
        }
        self.help_topic_var = ctk.StringVar(value="General Overview & Guide")
        self.help_menu = VisibleOptionMenu(
            help_top_row,
            values=list(self.help_topics_map.keys()),
            variable=self.help_topic_var,
            command=self._on_help_topic_changed,
            width=320,
            height=28,
        )
        self.help_menu.pack(side="left", padx=6)

        self.help_text = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Courier", size=13),
            wrap="none",
        )
        self.help_text.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._update_help_text("overview")

    # ------------------------------------------------------------------ #
    # File Operations & Workload Editor
    # ------------------------------------------------------------------ #
    def _load_initial_workload(self):
        candidate = "program.txt"
        if os.path.isfile(candidate):
            self._load_file(candidate)
        else:
            self.current_filepath = None
            self.file_status_label.configure(text="(Untitled Workload)")
            self.editor_text.delete("1.0", ctk.END)
            self.editor_text.insert(ctk.END, DEFAULT_STARTER_WORKLOAD)
            self._update_line_numbers()
            self.editor_status.configure(text="New starter template loaded.")

    def _load_file(self, filepath: str):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.current_filepath = filepath
            rel = os.path.relpath(filepath, os.getcwd())
            display_name = rel if not rel.startswith("..") else filepath
            self.file_status_label.configure(text=display_name)
            self._suppress_status_update = True
            self.editor_text.delete("1.0", ctk.END)
            self.editor_text.insert(ctk.END, content)
            self._suppress_status_update = False
            self._update_line_numbers()
            line_count = len(content.splitlines())
            self.editor_status.configure(text=f"Loaded {os.path.basename(filepath)} ({line_count} lines).")
        except Exception as e:
            messagebox.showerror("Error Opening File", f"Could not read {filepath}:\n{e}")

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Open Workload File",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if filename:
            self._load_file(filename)
            self.tabview.set("📝 Editor")

    def new_file(self):
        self.current_filepath = None
        self.file_status_label.configure(text="(Untitled Workload)")
        self.editor_text.delete("1.0", ctk.END)
        self.editor_text.insert(ctk.END, DEFAULT_STARTER_WORKLOAD)
        self._update_line_numbers()
        self.editor_status.configure(text="Created new starter workload.")
        self.tabview.set("📝 Editor")

    def save_file(self):
        if not self.current_filepath:
            return self.save_file_as()
        try:
            content = self.editor_text.get("1.0", ctk.END)
            with open(self.current_filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self.editor_status.configure(text=f"Saved {os.path.basename(self.current_filepath)} successfully.")
            return True
        except Exception as e:
            messagebox.showerror("Error Saving File", f"Could not save file:\n{e}")
            return False

    def save_file_as(self):
        filename = filedialog.asksaveasfilename(
            title="Save Workload As",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not filename:
            return False
        self.current_filepath = filename
        rel = os.path.relpath(filename, os.getcwd())
        self.file_status_label.configure(text=rel if not rel.startswith("..") else filename)
        return self.save_file()

    def _on_example_selected(self, choice: str):
        if choice == "Load Example...":
            return
        clean_choice = choice.split(" ")[0].strip()
        path = os.path.join(os.getcwd(), clean_choice)
        if os.path.isfile(path):
            self._load_file(path)
            self.tabview.set("📝 Editor")
        else:
            messagebox.showerror("Example Not Found", f"Could not find example file at:\n{path}")
        self.example_var.set("Load Example...")

    def validate_workload_syntax(self):
        text = self.editor_text.get("1.0", ctk.END)
        try:
            prog = parse_text(text, source=self.current_filepath or "<editor>")
            warnings = prog.validate()
            summary = f"✓ Syntax is valid!\n\nProcesses defined: {len(prog.processes)}\nDeclared resources: {len(prog.resources)}"
            if warnings:
                summary += "\n\nNon-fatal warnings:\n" + "\n".join(f"• {w}" for w in warnings)
                messagebox.showwarning("Validation with Warnings", summary)
            else:
                messagebox.showinfo("Validation Succeeded", summary)
            self.editor_status.configure(text="Syntax check passed.")
            return True
        except ParseError as e:
            messagebox.showerror("Syntax Error", f"Workload syntax error:\n\n{e}\n\nTip: Click '📖 Syntax Guide' for instructions and examples.")
            self.editor_status.configure(text=f"Syntax error: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Event Handlers & Configuration
    # ------------------------------------------------------------------ #
    def _on_algo_changed(self, choice: str):
        key = choice.split(" ")[0]
        if key == "rr":
            self.quantum_entry.configure(state="normal")
            self.quantum_label.configure(text="Round Robin Quantum (-q): [Active]")
        else:
            self.quantum_entry.configure(state="disabled")
            self.quantum_label.configure(text="Round Robin Quantum (-q): (RR only)")

    def _on_help_topic_changed(self, choice: str):
        topic_key = self.help_topics_map.get(choice, "overview")
        self._update_help_text(topic_key)

    def _update_help_text(self, topic: str):
        self.help_text.delete("1.0", ctk.END)
        if topic == "overview":
            self.help_text.insert(ctk.END, general_help())
        elif topic == "syntax":
            self.help_text.insert(ctk.END, WORKLOAD_SYNTAX_GUIDE)
        elif topic in ORDER:
            self.help_text.insert(ctk.END, algorithm_help(topic))
        else:
            self.help_text.insert(ctk.END, general_help())

    def _change_appearance_mode(self, mode: str):
        ctk.set_appearance_mode(mode)

    # ------------------------------------------------------------------ #
    # Simulation Execution
    # ------------------------------------------------------------------ #
    def _get_program_from_editor(self):
        text = self.editor_text.get("1.0", ctk.END).strip()
        if not text:
            messagebox.showerror("Empty Workload", "Please enter or open a workload in the Editor first.")
            return None
        try:
            program = parse_text(text, source=self.current_filepath or "<editor>")
            return program
        except ParseError as exc:
            messagebox.showerror("Parse Error", f"Could not parse workload:\n\n{exc}\n\nClick '📖 Syntax Guide' on the Editor toolbar for guidance.")
            self.tabview.set("📝 Editor")
            return None

    def _build_sim_config(self):
        avoidance_key = self.avoidance_map.get(self.avoidance_var.get(), "none")
        avoidance = None if avoidance_key == "none" else avoidance_key

        recovery_key = self.recovery_map.get(self.recovery_var.get(), "terminate")
        victim_key = self.victim_map.get(self.victim_var.get(), "resources")

        interactive = (recovery_key == "manual")
        self._last_deadlock_info = ""

        def _output_handler(msg: str):
            if "deadlock" in msg.lower() or "held resources" in msg.lower():
                self._last_deadlock_info += "\n" + msg.strip()

        config = SimConfig(
            avoidance=avoidance,
            deadlock_policy=recovery_key,
            victim_policy=victim_key,
            interactive=interactive,
            input_fn=self._gui_deadlock_input,
            output_fn=_output_handler,
            verbose=True,
        )
        return config

    def _gui_deadlock_input(self, prompt: str) -> str:
        """Prompt user in GUI when manual deadlock recovery is triggered."""
        clean_prompt = prompt.strip()
        info_prefix = self._last_deadlock_info.strip()
        if info_prefix:
            dialog_text = f"Deadlock Detected!\n{info_prefix}\n\n{clean_prompt}\n(Enter resource id like 1 or R1, or leave blank to auto-terminate victim):"
        else:
            dialog_text = f"Deadlock Detected!\n\n{clean_prompt}\n(Enter resource id like 1 or R1, or leave blank to auto-terminate victim):"

        try:
            dialog = ctk.CTkInputDialog(
                text=dialog_text,
                title="Manual Deadlock Resolution",
            )
            val = dialog.get_input()
            return val.strip() if val else ""
        except Exception:
            val = simpledialog.askstring("Manual Deadlock Resolution", dialog_text, parent=self)
            return val.strip() if val else ""

    def run_simulation(self):
        program = self._get_program_from_editor()
        if program is None:
            return

        algo_key = self.algo_var.get().split(" ")[0]
        try:
            quantum = float(self.quantum_var.get())
            if quantum <= 0:
                quantum = 4.0
        except ValueError:
            messagebox.showerror("Invalid Value", "Round Robin Quantum must be a positive number.")
            return

        config = self._build_sim_config()

        try:
            sim = simulate(program, algorithm=algo_key, quantum=quantum, config=config)
            self.last_sim = sim
            self.last_algo = algo_key
            self.last_source = self.current_filepath or program.source
            self.is_comparison_mode = False

            self.display_single_results(sim, algo_key, program.source)
            self.tabview.set("📊 Metrics")
        except Exception as e:
            messagebox.showerror("Simulation Error", f"An error occurred during simulation:\n{e}")

    def run_compare_all(self):
        program = self._get_program_from_editor()
        if program is None:
            return

        try:
            quantum = float(self.quantum_var.get())
            if quantum <= 0:
                quantum = 4.0
        except ValueError:
            quantum = 4.0

        config = self._build_sim_config()

        try:
            runs = {}
            sims = {}
            for name in ORDER:
                s = simulate(program, algorithm=name, quantum=quantum, config=config)
                runs[name] = s.metrics()
                sims[name] = s

            names = {n: display_name(n) for n in ORDER}
            self.last_comparison = (runs, sims, names)
            self.last_sim = sims[ORDER[0]]
            self.last_algo = ORDER[0]
            self.last_source = self.current_filepath or program.source
            self.is_comparison_mode = True

            header = f"Algorithm comparison for {self.last_source}\n{'=' * (25 + len(self.last_source))}"
            full_table = comparison_table(runs, names)
            text = f"{header}\n\n{full_table}\n"

            self.comparison_text.delete("1.0", ctk.END)
            self.comparison_text.insert(ctk.END, text)

            self.display_single_results(sims[ORDER[0]], ORDER[0], self.last_source)
            self.tabview.set("📈 Comparison")
        except Exception as e:
            messagebox.showerror("Comparison Error", f"Failed to run algorithm comparison:\n{e}")

    def display_single_results(self, sim, algo_key: str, source: str):
        # 1. Metrics Tab
        self.metrics_text.delete("1.0", ctk.END)
        metrics_header = (
            f"SIMULATION REPORT - {display_name(algo_key).upper()}\n"
            f"Workload: {source}\n"
            f"{'=' * 50}\n\n"
        )
        self.metrics_text.insert(ctk.END, metrics_header)
        self.metrics_text.insert(ctk.END, "Aggregate Metrics:\n")
        self.metrics_text.insert(ctk.END, format_metrics(sim.metrics()))

        if sim.force_released:
            self.metrics_text.insert(ctk.END, "\n\nForce-Released Resources (Deadlock recovery):\n")
            for rid, owner in sim.force_released:
                self.metrics_text.insert(ctk.END, f"  • R{rid} taken from {owner}\n")

        if sim.aborted:
            self.metrics_text.insert(ctk.END, "\n\n⚠ WARNING: Simulation ended early (deadlock or step budget)!\n")

        # 2. Process Table Tab
        self.process_text.delete("1.0", ctk.END)
        rows = []
        for row in sim.process_rows():
            rows.append([
                row["name"],
                row["priority"],
                row["arrival"],
                row["start"],
                row["finish"],
                row["burst"],
                row["io"],
                row["turnaround"],
                row["waiting"],
                row["response"],
            ])
        ptable = table(
            ["Process", "Prio", "Arrival", "Start", "Finish", "Burst", "I/O",
             "Turnaround", "Waiting", "Response"],
            rows,
        )
        self.process_text.insert(ctk.END, ptable)

        # 3. Timeline Tab
        self.timeline_text.delete("1.0", ctk.END)
        gantt = render_gantt(sim.timeline, width=88)
        self.timeline_text.insert(ctk.END, gantt)

        # 4. Logs Tab
        self.logs_text.delete("1.0", ctk.END)
        trace_rows = [
            [f"{e.time:g}", e.process, e.action,
             f"R{e.resource}" if e.resource is not None else "",
             e.detail or ""]
            for e in sim.events
        ]
        log_table = table(["Time", "Process", "Action", "Resource", "Detail"], trace_rows)
        self.logs_text.insert(ctk.END, log_table)

    # ------------------------------------------------------------------ #
    # Exporting Reports
    # ------------------------------------------------------------------ #
    def export_report(self):
        if not self.last_sim and not self.last_comparison:
            messagebox.showinfo("Export", "Please run a simulation or comparison first.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Export Simulation Report")
        dialog.geometry("380x230")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="Choose Report Export Format:",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(padx=20, pady=(16, 12))

        fmt_var = ctk.StringVar(value="txt")

        radio_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        radio_frame.pack(padx=20, pady=4, fill="x")

        ctk.CTkRadioButton(radio_frame, text="Plain Text Report (.txt)", variable=fmt_var, value="txt").pack(anchor="w", pady=4)
        ctk.CTkRadioButton(radio_frame, text="JSON Machine-Readable (.json)", variable=fmt_var, value="json").pack(anchor="w", pady=4)
        ctk.CTkRadioButton(radio_frame, text="CSV Process Metrics (.csv)", variable=fmt_var, value="csv").pack(anchor="w", pady=4)

        def do_export():
            fmt = fmt_var.get()
            dialog.destroy()
            self._save_export_file(fmt)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(padx=20, pady=(16, 10), fill="x")

        ctk.CTkButton(btn_row, text="Cancel", width=90, fg_color="gray", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btn_row, text="Save As...", width=100, command=do_export).pack(side="right")

    def _save_export_file(self, fmt: str):
        ext_map = {"txt": ".txt", "json": ".json", "csv": ".csv"}
        types_map = {
            "txt": [("Text Files", "*.txt"), ("All Files", "*.*")],
            "json": [("JSON Files", "*.json"), ("All Files", "*.*")],
            "csv": [("CSV Files", "*.csv"), ("All Files", "*.*")],
        }

        filename = filedialog.asksaveasfilename(
            title="Export Report As",
            defaultextension=ext_map[fmt],
            filetypes=types_map[fmt],
        )
        if not filename:
            return

        try:
            content = ""
            if self.is_comparison_mode and self.last_comparison:
                runs, sims, names = self.last_comparison
                if fmt == "json":
                    import json
                    payload = {
                        "workload": self.last_source,
                        "comparison": runs,
                        "runs": {n: to_dict(sims[n], names[n], self.last_source) for n in ORDER},
                    }
                    content = json.dumps(payload, indent=2)
                elif fmt == "csv":
                    content = to_csv(sims[ORDER[0]])
                else:
                    header = f"Algorithm comparison for {self.last_source}\n{'=' * (25 + len(self.last_source))}"
                    content = header + "\n\n" + comparison_table(runs, names) + "\n"
            else:
                if fmt == "json":
                    content = to_json(self.last_sim, display_name(self.last_algo), self.last_source)
                elif fmt == "csv":
                    content = to_csv(self.last_sim)
                else:
                    content = format_report(self.last_sim, display_name(self.last_algo), self.last_source)

            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")

            messagebox.showinfo("Export Successful", f"Report successfully written to:\n{filename}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not write export file:\n{e}")


def main():
    app = SimulatorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    main()
