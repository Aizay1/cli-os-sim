import threading
import time
from collections import defaultdict, deque
import sys

class ProcessInfo:
    def __init__(self, name, cmds):
        self.name = name
        self.cmds = list(cmds)
        self.estimated_burst = self.estimate_length()
        self.start_time = None
        self.finish_time = None
        self.turnaround = None

    def estimate_length(self):
        length = 0
        for cmd in self.cmds:
            if cmd.startswith("wait"):
                seconds = int(cmd.split("(")[1].replace(")", ""))
                length += seconds
            elif cmd.startswith("resource"):
                length += 1
        return length

class ActionLogEntry:
    def __init__(self, timestamp, process, action, resource=None, note=None):
        self.timestamp = timestamp
        self.process = process
        self.action = action
        self.resource = resource
        self.note = note

    def __str__(self):
        ts = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        res = f"R{self.resource}" if self.resource is not None else ""
        note = f"({self.note})" if self.note else ""
        return f"{ts:<10} {self.process:<8} {self.action:<25} {res:<5} {note}"

class EnhancedPseudoOSSim:
    def __init__(self, filename):
        self.filename = filename
        self.locks = [threading.Lock() for _ in range(10)]
        self.resource_owner = {}
        self.waiting_for = defaultdict(list)
        self.programs = {}
        self.process_infos = []
        self.completed = set()
        self.force_released = set()
        self.lock = threading.Lock()
        self.running = True
        self.process_table = []
        self.action_log = []

    def log_action(self, process, action, resource=None, note=None):
        self.action_log.append(ActionLogEntry(time.time(), process, action, resource, note))

    def parse_file(self):
        current = None
        pname = None
        try:
            with open(self.filename) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("program"):
                        pname = line.split()[1]
                        current = []
                        self.programs[pname] = current
                    elif current is not None:
                        current.append(line)
            self.process_infos = [ProcessInfo(name, cmds) for name, cmds in self.programs.items()]
        except FileNotFoundError:
            print(f"Error: File '{self.filename}' not found.")
            sys.exit(1)

    def print_status(self):
        print("\n📋 Current Resource Allocation:")
        for i in range(len(self.locks)):
            with self.lock:
                owner = self.resource_owner.get(i, "None")
            print(f"  R{i}: {owner}")
        print("📥 Waiting List:")
        with self.lock:
            for p, resources in self.waiting_for.items():
                if resources:
                    print(f"  {p} -> {', '.join('R'+str(r) for r in resources)}")
        print()
    def run_program(self, procinfo, record_times=True):
        name = procinfo.name
        cmds = procinfo.cmds
        try:
            if record_times:
                procinfo.start_time = time.time()
            for cmd in cmds:
                if not self.running:
                    break
                if cmd.startswith("resource"):
                    parts = cmd.replace("resource", "").replace("(", "").replace(")", "").split(",")
                    res_id = int(parts[0])
                    op = parts[1].strip()
                    if op == "allocate":
                        with self.lock:
                            print(f"{name} requests R{res_id}")
                            self.log_action(name, "requests resource", res_id)
                            acquired = self.locks[res_id].acquire(blocking=False)
                            if acquired:
                                print(f"{name} successfully allocated R{res_id}")
                                self.log_action(name, "allocated resource", res_id)
                                self.resource_owner[res_id] = name
                            else:
                                print(f"{name} is blocked waiting for R{res_id}")
                                self.log_action(name, "blocked on resource", res_id)
                                self.waiting_for[name].append(res_id)
                        if not acquired:
                            deadlock_reported = False
                            while not self.locks[res_id].acquire(timeout=1):
                                if not self.running:
                                    return
                                if self.detect_deadlock(name) and not deadlock_reported:
                                    print(f"\n💥 Deadlock detected involving: {', '.join(self.waiting_for.keys())}")
                                    self.log_action("SYSTEM", "deadlock detected", note=f"Involving {', '.join(self.waiting_for.keys())}")
                                    self.print_status()
                                    deadlock_reported = True
                                    try:
                                        release_id = int(input("Enter the resource ID (e.g. 1 for R1) to release: "))
                                        self.force_release(release_id)
                                    except Exception as e:
                                        print(f"⚠️ Invalid input: {e}. Skipping release prompt.")
                                        continue
                            with self.lock:
                                print(f"{name} acquired R{res_id} after wait")
                                self.log_action(name, "acquired after wait", res_id)
                                self.resource_owner[res_id] = name
                                if name in self.waiting_for and res_id in self.waiting_for[name]:
                                    self.waiting_for[name].remove(res_id)
                elif cmd.startswith("wait"):
                    seconds = int(cmd.split("(")[1].replace(")", ""))
                    print(f"{name} waits for {seconds} seconds")
                    self.log_action(name, "waits", note=f"{seconds} seconds")
                    time.sleep(seconds)
                elif cmd.startswith("for") or cmd.startswith("next"):
                    continue
                elif cmd == "end":
                    print(f"{name} ends and releases all resources")
                    self.log_action(name, "ends and releases all resources")
                    self.release_all(name)
                    self.completed.add(name)
                    break
            if record_times:
                procinfo.finish_time = time.time()
                procinfo.turnaround = procinfo.finish_time - procinfo.start_time
                self.process_table.append(procinfo)
        except Exception as e:
            print(f"Error in program {name}: {e}")
            self.running = False


    def release_all(self, name):
        with self.lock:
            for res_id, owner in list(self.resource_owner.items()):
                if owner == name:
                    self.locks[res_id].release()
                    print(f"{name} released R{res_id}")
                    self.log_action(name, "released resource", res_id)
                    del self.resource_owner[res_id]
            if name in self.waiting_for:
                del self.waiting_for[name]

    def force_release(self, res_id):
        with self.lock:
            if res_id in self.resource_owner:
                owner = self.resource_owner[res_id]
                print(f"⚠️ Force releasing R{res_id} from {owner}")
                self.log_action("SYSTEM", "force released resource", res_id, f"from {owner}")
                self.locks[res_id].release()
                del self.resource_owner[res_id]
                self.force_released.add((res_id, owner))
                if owner in self.waiting_for and res_id in self.waiting_for[owner]:
                    self.waiting_for[owner].remove(res_id)

    def detect_deadlock(self, current_process=None):
        with self.lock:
            graph = defaultdict(set)
            for process, resources in self.waiting_for.items():
                for res_id in resources:
                    if res_id in self.resource_owner:
                        owner = self.resource_owner[res_id]
                        graph[process].add(owner)
            visited = set()
            recursion_stack = set()
            def has_cycle(node):
                visited.add(node)
                recursion_stack.add(node)
                for neighbor in graph.get(node, set()):
                    if neighbor not in visited:
                        if has_cycle(neighbor):
                            return True
                    elif neighbor in recursion_stack:
                        return True
                recursion_stack.remove(node)
                return False
            for process in list(graph.keys()):
                if process not in visited:
                    if has_cycle(process):
                        return True
            return False

    def run_all(self, scheduling='fcfs', sjf_type='nonpreemptive', quantum=2):
        self.completed = set()
        self.process_table = []

        if scheduling == 'rr':
            class RRProcess:
                def __init__(self, procinfo):
                    self.name = procinfo.name
                    self.cmds = list(procinfo.cmds)
                    self.pc = 0
                    self.start_time = None
                    self.finish_time = None
                    self.turnaround = None
                    self.remaining_quantum = quantum
                    self.blocked = False
                    self.blocked_resource = None
                    self.wait_remaining = 0

            processes = [RRProcess(ProcessInfo(name, cmds)) for name, cmds in self.programs.items()]
            ready_queue = deque(processes)
            finished = []

            while ready_queue:
                current = ready_queue.popleft()

                if current.pc >= len(current.cmds):
                    if not current.finish_time:
                        current.finish_time = time.time()
                        current.turnaround = current.finish_time - current.start_time
                        finished.append(current)
                        self.completed.add(current.name)
                    continue

                if current.start_time is None:
                    current.start_time = time.time()
                    print(f"\n⏱️ {current.name} started execution")
                    self.log_action(current.name, "started execution", note="[RR]")

                if current.blocked:
                    res_id = current.blocked_resource
                    with self.lock:
                        acquired = self.locks[res_id].acquire(blocking=False)
                        if acquired:
                            print(f"🔓 {current.name} acquired R{res_id} after waiting")
                            self.resource_owner[res_id] = current.name
                            if current.name in self.waiting_for and res_id in self.waiting_for[current.name]:
                                self.waiting_for[current.name].remove(res_id)
                            current.blocked = False
                            current.blocked_resource = None
                            self.log_action(current.name, "acquired resource after wait", res_id, "[RR]")
                        else:
                            ready_queue.append(current)
                            continue

                while current.pc < len(current.cmds) and current.remaining_quantum > 0 and not current.blocked:
                    cmd = current.cmds[current.pc]

                    if cmd.startswith("wait"):
                        if current.wait_remaining == 0:
                            current.wait_remaining = int(cmd.split("(")[1].replace(")", ""))
                        exec_time = min(current.wait_remaining, current.remaining_quantum)
                        print(f"⏳ {current.name} waits for {exec_time} seconds [RR]")
                        self.log_action(current.name, "waits", note=f"{exec_time} seconds [RR]")
                        time.sleep(exec_time)
                        current.wait_remaining -= exec_time
                        current.remaining_quantum -= exec_time
                        if current.wait_remaining == 0:
                            current.pc += 1

                    elif cmd.startswith("resource"):
                        parts = cmd.replace("resource", "").replace("(", "").replace(")", "").split(",")
                        res_id = int(parts[0])
                        op = parts[1].strip()
                        
                        if op == "allocate":
                            print(f"🔑 {current.name} requests R{res_id}")
                            self.log_action(current.name, "requests resource", res_id, "[RR]")
                            with self.lock:
                                acquired = self.locks[res_id].acquire(blocking=False)
                                if acquired:
                                    print(f"✅ {current.name} allocated R{res_id}")
                                    self.log_action(current.name, "allocated resource", res_id, "[RR]")
                                    self.resource_owner[res_id] = current.name
                                    current.pc += 1
                                    current.remaining_quantum -= 1
                                else:
                                    print(f"🚧 {current.name} blocked on R{res_id}")
                                    self.log_action(current.name, "blocked on resource", res_id, "[RR]")
                                    current.blocked = True
                                    current.blocked_resource = res_id
                                    self.waiting_for[current.name].append(res_id)
                                    break

                    elif cmd == "end":
                        print(f"🏁 {current.name} completed!")
                        self.log_action(current.name, "ends and releases all resources", note="[RR]")
                        self.release_all(current.name)
                        current.finish_time = time.time()
                        current.turnaround = current.finish_time - current.start_time
                        finished.append(current)
                        self.completed.add(current.name)
                        current.pc += 1
                        break

                    else:
                        current.pc += 1

                if current.pc >= len(current.cmds) and not current.finish_time:
                    current.finish_time = time.time()
                    current.turnaround = current.finish_time - current.start_time
                    finished.append(current)
                    self.completed.add(current.name)
                    continue

                if not current.blocked and current.pc < len(current.cmds):
                    current.remaining_quantum = quantum
                    ready_queue.append(current)
                    print(f"↻ {current.name} re-queued (remaining commands: {len(current.cmds)-current.pc})")
                elif current.blocked:
                    ready_queue.append(current)
                    print(f"⏸️ {current.name} remains blocked on R{current.blocked_resource}")

                    if ready_queue and all(p.blocked for p in ready_queue):
                        print("\n💀 Deadlock detected!")
                        self.log_action("SYSTEM", "deadlock detected", note="[RR]")
                        self.print_status()
                        
                        # Build the full wait-for graph to find all resources in the cycle
                        with self.lock:
                            graph = defaultdict(set)
                            for process, resources in self.waiting_for.items():
                                for res_id in resources:
                                    if res_id in self.resource_owner:
                                        owner = self.resource_owner[res_id]
                                        graph[process].add(owner)
                            
                            # Find all resources in the cycle
                            resources_in_cycle = set()
                            for process in graph:
                                for owner in graph[process]:
                                    if owner in graph:  # If the owner is also waiting for something
                                        resources_in_cycle.add(self.waiting_for[owner][0])  # Get first resource they're waiting for

                        # Ask user to break the deadlock by releasing one resource
                        while True:
                            try:
                                print(f"Resources involved in deadlock: {', '.join(f'R{r}' for r in sorted(resources_in_cycle))}")
                                release_id = int(input("Enter resource ID to release (0-9): "))
                                if release_id in resources_in_cycle:
                                    break
                                print(f"⚠️ Please enter one of the involved resource IDs: {sorted(resources_in_cycle)}")
                            except ValueError:
                                print("⚠️ Invalid input. Please enter a number between 0 and 9")

                        # Automatically resolve the entire chain after first release
                        while True:
                            # Release the selected resource
                            self.force_release(release_id)
                            
                            # Find and unblock processes waiting for this resource
                            unblocked = []
                            for p in ready_queue:
                                if p.blocked and p.blocked_resource == release_id:
                                    p.blocked = False
                                    if p.name in self.waiting_for and release_id in self.waiting_for[p.name]:
                                        self.waiting_for[p.name].remove(release_id)
                                    unblocked.append(p)
                            
                            # If no processes were unblocked, we're done
                            if not unblocked:
                                break
                                
                            # Try to assign the resource to the first unblocked process
                            with self.lock:
                                for p in unblocked:
                                    acquired = self.locks[release_id].acquire(blocking=False)
                                    if acquired:
                                        self.resource_owner[release_id] = p.name
                                        print(f"✅ {p.name} acquired R{release_id} after release")
                                        self.log_action(p.name, "acquired resource after release", release_id, "[RR]")
                                        p.blocked_resource = None
                                        p.pc += 1  # Move past the allocation command
                                        
                                        # If this process completes, it will release its resources
                                        if p.pc >= len(p.cmds):
                                            p.finish_time = time.time()
                                            p.turnaround = p.finish_time - p.start_time
                                            finished.append(p)
                                            self.completed.add(p.name)
                                            self.release_all(p.name)
                                        
                                        # The next resource to release is whatever this process was holding
                                        for res_id, owner in list(self.resource_owner.items()):
                                            if owner == p.name:
                                                release_id = res_id
                                                break
                                        break
                            
                            print(f"♻️ Automatically releasing R{release_id} next")
    

            for proc in finished:
                pi = ProcessInfo(proc.name, [])
                pi.start_time = proc.start_time
                pi.finish_time = proc.finish_time
                pi.turnaround = proc.turnaround
                self.process_table.append(pi)
        else:
            if scheduling == 'fcfs':
                order = self.process_infos
                for procinfo in order:
                    self.run_program(procinfo)
            elif scheduling == 'sjf':
                order = sorted(self.process_infos, key=lambda x: x.estimated_burst)
                if sjf_type == 'nonpreemptive':
                    for procinfo in order:
                        self.run_program(procinfo)
                elif sjf_type == 'preemptive':
                    ready = [ProcessInfo(p.name, list(p.cmds)) for p in order]
                    finished = []
                    while ready:
                        ready.sort(key=lambda x: x.estimate_length())
                        proc = ready[0]
                        if proc.start_time is None:
                            proc.start_time = time.time()
                        if proc.cmds:
                            cmd = proc.cmds.pop(0)
                            if cmd.startswith("wait"):
                                seconds = int(cmd.split("(")[1].replace(")", ""))
                                print(f"{proc.name} waits for {seconds} seconds [preemptive SJF]")
                                self.log_action(proc.name, "waits", note=f"{seconds} seconds [SJF]")
                                time.sleep(seconds)
                            elif cmd.startswith("resource"):
                                parts = cmd.replace("resource", "").replace("(", "").replace(")", "").split(",")
                                res_id = int(parts[0])
                                op = parts[1].strip()
                                if op == "allocate":
                                    with self.lock:
                                        print(f"{proc.name} requests R{res_id}")
                                        self.log_action(proc.name, "requests resource", res_id, "[SJF]")
                                        acquired = self.locks[res_id].acquire(blocking=False)
                                        if acquired:
                                            print(f"{proc.name} successfully allocated R{res_id}")
                                            self.log_action(proc.name, "allocated resource", res_id, "[SJF]")
                                            self.resource_owner[res_id] = proc.name
                                        else:
                                            print(f"{proc.name} is blocked waiting for R{res_id}")
                                            self.log_action(proc.name, "blocked on resource", res_id, "[SJF]")
                                            self.waiting_for[proc.name].append(res_id)
                                    if not acquired:
                                        deadlock_reported = False
                                        while not self.locks[res_id].acquire(timeout=1):
                                            if not self.running:
                                                return
                                            if self.detect_deadlock(proc.name) and not deadlock_reported:
                                                print(f"\n💥 Deadlock detected involving: {', '.join(self.waiting_for.keys())}")
                                                self.log_action("SYSTEM", "deadlock detected", note=f"Involving {', '.join(self.waiting_for.keys())} [SJF]")
                                                self.print_status()
                                                deadlock_reported = True
                                                try:
                                                    release_id = int(input("Enter the resource ID (e.g. 1 for R1) to release: "))
                                                    self.force_release(release_id)
                                                except Exception as e:
                                                    print(f"⚠️ Invalid input: {e}. Skipping release prompt.")
                                                    continue
                                        with self.lock:
                                            print(f"{proc.name} acquired R{res_id} after wait")
                                            self.log_action(proc.name, "acquired after wait", res_id, "[SJF]")
                                            self.resource_owner[res_id] = proc.name
                                            if proc.name in self.waiting_for and res_id in self.waiting_for[proc.name]:
                                                self.waiting_for[proc.name].remove(res_id)
                            elif cmd == "end":
                                print(f"{proc.name} ends and releases all resources [preemptive SJF]")
                                self.log_action(proc.name, "ends and releases all resources", note="[SJF]")
                                self.release_all(proc.name)
                                proc.finish_time = time.time()
                                proc.turnaround = proc.finish_time - proc.start_time
                                finished.append(proc)
                                ready.pop(0)
                                continue
                        if not proc.cmds:
                            proc.finish_time = time.time()
                            proc.turnaround = proc.finish_time - proc.start_time
                            finished.append(proc)
                            ready.pop(0)
                    self.process_table.extend(finished)

        self.summary()

    def summary(self):
        print("\n✅ Simulation Complete!")
        print("🟢 Completed Processes:", ", ".join(sorted(self.completed)))
        print("🔓 Final Resource Allocation:")
        for i in range(len(self.locks)):
            with self.lock:
                owner = self.resource_owner.get(i, "None")
            print(f"  R{i}: {owner}")
        if self.force_released:
            print("⚠️ Force Released Resources:")
            for rid, proc in self.force_released:
                print(f"  R{rid} was released from {proc}")

        print("\n📊 Process Completion Table:")
        print(f"{'Process':<10}{'Start':<20}{'Finish':<20}{'Turnaround (s)':<15}{'Burst Est.':<10}")
        for proc in self.process_table:
            start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.start_time)) if proc.start_time else "-"
            finish = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.finish_time)) if proc.finish_time else "-"
            print(f"{proc.name:<10}{start:<20}{finish:<20}{proc.turnaround:<15.2f}{proc.estimated_burst:<10}")

        print("\n📊 Action Log Table:")
        print(f"{'Time':<10} {'Process':<8} {'Action':<25} {'Res':<5} {'Note'}")
        for entry in self.action_log:
            print(entry)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 ps-runner.py program.txt")
        sys.exit(1)

    sim = EnhancedPseudoOSSim(sys.argv[1])
    sim.parse_file()
    print("Choose scheduling algorithm:")
    print("1. First-Come-First-Serve (FCFS)")
    print("2. Shortest Job First (SJF)")
    print("3. Round Robin (RR)")
    choice = input("Enter choice (1/2/3): ").strip()

    if choice == '1':
        sim.run_all(scheduling='fcfs')
    elif choice == '2':
        print("SJF selected. Choose type:")
        print("1. Non-preemptive")
        print("2. Preemptive (SRTF)")
        sjf_choice = input("Enter choice (1/2): ").strip()
        if sjf_choice == '2':
            sim.run_all(scheduling='sjf', sjf_type='preemptive')
        else:
            sim.run_all(scheduling='sjf', sjf_type='nonpreemptive')
    elif choice == '3':
        quantum = input("Enter time quantum (seconds, default=2): ").strip()
        try:
            quantum = int(quantum)
        except:
            quantum = 2
        sim.run_all(scheduling='rr', quantum=quantum)
    else:
        print("Invalid choice, defaulting to FCFS")
        sim.run_all(scheduling='fcfs')
