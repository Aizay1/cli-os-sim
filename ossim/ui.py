import os
import sys
import customtkinter as ctk
from tkinter import filedialog, messagebox

from ossim import parse_file, simulate, SimConfig
from ossim.report import format_metrics, table, render_gantt

# Set appearance mode and color theme
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class SimulatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("OS Simulator UI")
        self.geometry("1100x700")

        # configure grid layout (1x2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(8, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="OS Simulator", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # File selection
        self.file_label = ctk.CTkLabel(self.sidebar_frame, text="Workload File:")
        self.file_label.grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        self.file_button = ctk.CTkButton(self.sidebar_frame, text="Browse...", command=self.browse_file)
        self.file_button.grid(row=2, column=0, padx=20, pady=(5, 10))
        self.file_path_var = ctk.StringVar(value="")
        
        # Display the file path compactly
        self.file_path_label = ctk.CTkLabel(self.sidebar_frame, textvariable=self.file_path_var, font=ctk.CTkFont(size=11), text_color="gray", wraplength=200)
        self.file_path_label.grid(row=3, column=0, padx=20, pady=0, sticky="w")

        # Algorithm selection
        self.algo_label = ctk.CTkLabel(self.sidebar_frame, text="Algorithm:")
        self.algo_label.grid(row=4, column=0, padx=20, pady=(10, 0), sticky="w")
        self.algo_var = ctk.StringVar(value="fcfs")
        algorithms = ["fcfs", "sjf", "srtf", "rr", "priority", "priority-p", "hrrn"]
        self.algo_optionmenu = ctk.CTkOptionMenu(self.sidebar_frame, values=algorithms, variable=self.algo_var, command=self.algo_changed)
        self.algo_optionmenu.grid(row=5, column=0, padx=20, pady=(5, 10))

        # Quantum (for RR)
        self.quantum_label = ctk.CTkLabel(self.sidebar_frame, text="Quantum (for RR):")
        self.quantum_label.grid(row=6, column=0, padx=20, pady=(10, 0), sticky="w")
        self.quantum_var = ctk.StringVar(value="4")
        self.quantum_entry = ctk.CTkEntry(self.sidebar_frame, textvariable=self.quantum_var)
        self.quantum_entry.grid(row=7, column=0, padx=20, pady=(5, 10))
        self.quantum_entry.configure(state="disabled") # Disabled by default

        # Deadlock handling
        self.deadlock_label = ctk.CTkLabel(self.sidebar_frame, text="Deadlock Handling:")
        self.deadlock_label.grid(row=8, column=0, padx=20, pady=(10, 0), sticky="sw")
        
        self.avoidance_var = ctk.StringVar(value="none")
        self.avoidance_switch = ctk.CTkSwitch(self.sidebar_frame, text="Banker's Avoidance", variable=self.avoidance_var, onvalue="banker", offvalue="none")
        self.avoidance_switch.grid(row=9, column=0, padx=20, pady=(5, 5), sticky="w")

        self.recovery_var = ctk.StringVar(value="terminate")
        self.recovery_menu = ctk.CTkOptionMenu(self.sidebar_frame, values=["terminate", "preempt"], variable=self.recovery_var)
        self.recovery_menu.grid(row=10, column=0, padx=20, pady=(5, 20))

        # Run Button
        self.run_button = ctk.CTkButton(self.sidebar_frame, text="Run Simulation", command=self.run_simulation, fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"))
        self.run_button.grid(row=11, column=0, padx=20, pady=(10, 20), sticky="s")

        # --- Main Content Area ---
        self.tabview = ctk.CTkTabview(self, width=800)
        self.tabview.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.tabview.add("Metrics")
        self.tabview.add("Process Table")
        self.tabview.add("Timeline")
        self.tabview.add("Logs")

        self.tabview.tab("Metrics").grid_columnconfigure(0, weight=1)
        self.tabview.tab("Metrics").grid_rowconfigure(0, weight=1)
        self.metrics_text = ctk.CTkTextbox(self.tabview.tab("Metrics"), font=ctk.CTkFont(family="Courier", size=13))
        self.metrics_text.grid(row=0, column=0, sticky="nsew")

        self.tabview.tab("Process Table").grid_columnconfigure(0, weight=1)
        self.tabview.tab("Process Table").grid_rowconfigure(0, weight=1)
        self.process_text = ctk.CTkTextbox(self.tabview.tab("Process Table"), font=ctk.CTkFont(family="Courier", size=13), wrap="none")
        self.process_text.grid(row=0, column=0, sticky="nsew")

        self.tabview.tab("Timeline").grid_columnconfigure(0, weight=1)
        self.tabview.tab("Timeline").grid_rowconfigure(0, weight=1)
        self.timeline_text = ctk.CTkTextbox(self.tabview.tab("Timeline"), font=ctk.CTkFont(family="Courier", size=13), wrap="none")
        self.timeline_text.grid(row=0, column=0, sticky="nsew")

        self.tabview.tab("Logs").grid_columnconfigure(0, weight=1)
        self.tabview.tab("Logs").grid_rowconfigure(0, weight=1)
        self.logs_text = ctk.CTkTextbox(self.tabview.tab("Logs"), font=ctk.CTkFont(family="Courier", size=13), wrap="none")
        self.logs_text.grid(row=0, column=0, sticky="nsew")

        # Initialize
        self.algo_changed("fcfs")

    def browse_file(self):
        filename = filedialog.askopenfilename(title="Select Workload File", filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if filename:
            # We want to display relative path if it's inside current directory
            try:
                rel_path = os.path.relpath(filename, os.getcwd())
                if not rel_path.startswith(".."):
                    self.file_path_var.set(rel_path)
                else:
                    self.file_path_var.set(filename)
            except Exception:
                self.file_path_var.set(filename)

    def algo_changed(self, choice):
        if choice == "rr":
            self.quantum_entry.configure(state="normal")
        else:
            self.quantum_entry.configure(state="disabled")

    def run_simulation(self):
        filename = self.file_path_var.get()
        if not filename:
            messagebox.showerror("Error", "Please select a workload file first.")
            return

        algo = self.algo_var.get()
        try:
            quantum = float(self.quantum_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid quantum value.")
            return

        avoidance = self.avoidance_var.get()
        if avoidance == "none":
            avoidance = None

        recovery = self.recovery_var.get()

        config = SimConfig(
            avoidance=avoidance,
            deadlock_policy=recovery,
            interactive=False,
            verbose=False
        )

        try:
            program = parse_file(filename)
            sim = simulate(program, algorithm=algo, quantum=quantum, config=config)
            self.display_results(sim)
        except Exception as e:
            messagebox.showerror("Simulation Error", str(e))

    def display_results(self, sim):
        # Metrics
        self.metrics_text.delete("1.0", ctk.END)
        self.metrics_text.insert(ctk.END, format_metrics(sim.metrics()))

        # Process Table
        self.process_text.delete("1.0", ctk.END)
        rows = []
        for row in sim.process_rows():
            rows.append([
                row["name"], row["priority"], row["arrival"], row["start"],
                row["finish"], row["burst"], row["io"], row["turnaround"],
                row["waiting"], row["response"]
            ])
        ptable = table(["Process", "Prio", "Arrival", "Start", "Finish", "Burst", "I/O",
         "Turnaround", "Waiting", "Response"], rows)
        self.process_text.insert(ctk.END, ptable)

        # Timeline
        self.timeline_text.delete("1.0", ctk.END)
        gantt = render_gantt(sim.timeline, width=90)
        self.timeline_text.insert(ctk.END, gantt)

        # Logs
        self.logs_text.delete("1.0", ctk.END)
        trace_rows = [
            [f"{e.time:g}", e.process, e.action,
             f"R{e.resource}" if e.resource is not None else "",
             e.detail or ""]
            for e in sim.events
        ]
        log_table = table(["Time", "Process", "Action", "Resource", "Detail"], trace_rows)
        self.logs_text.insert(ctk.END, log_table)

def main():
    app = SimulatorApp()
    app.mainloop()

if __name__ == "__main__":
    main()
