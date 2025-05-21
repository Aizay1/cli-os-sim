# EnhancedPseudoOSSim

A Python simulation of basic operating system process scheduling, resource allocation, and deadlock handling.

---

## Overview

This project simulates how an operating system manages multiple processes, resources, and deadlocks. It supports multiple scheduling algorithms and demonstrates how processes can request and release resources, wait, and how the system detects and resolves deadlocks.

### Key Features

- **Process Scheduling**  
  Supports First-Come-First-Serve (FCFS), Shortest Job First (SJF), and Round Robin (RR).

- **Resource Allocation**  
  Simulates processes requesting and releasing shared resources.

- **Deadlock Detection & Resolution**  
  Detects deadlocks and allows user intervention to resolve them. When a resource is force-released, the next waiting process automatically acquires it.

- **Action Logging**  
  Logs significant events and provides a summary of process execution at the end.

---

## How It Works

1. **Input File**  
   The simulation reads a text file (e.g., `program.txt`) that defines the sequence of actions for each process.

2. **Scheduling Choice**  
   When the program starts, the user selects a scheduling algorithm:
   - FCFS (First-Come-First-Serve)
   - SJF (Shortest Job First)
   - RR (Round Robin)

3. **Simulation**  
   - Each process executes its commands in the order determined by the selected scheduling strategy.
   - When a process requests a resource:
     - If the resource is available, it is allocated.
     - If not, the process is blocked and added to a waiting list.
   - **Deadlock Detection**  
     If a deadlock is detected, the user is prompted to select a resource to force-release. The next waiting process for that resource will automatically acquire it.
   - Processes can also execute `wait` commands (simulating computation time) and `end` commands (which release all held resources and terminate the process).

4. **Logging & Output**  
   - Each action and state change is printed during execution.
   - At the end, a summary table displays each process’s turnaround time.

---

## Example Usage

Run the simulation:

```bash
python3 ps-runner.py program.txt
```
You will be prompted to choose a scheduling algorithm:
```
Choose scheduling algorithm:
1. First-Come-First-Serve (FCFS)
2. Shortest Job First (SJF)
3. Round Robin (RR)
Enter choice (1/2/3): 1
```
If a deadlock is detected:
```
Deadlock detected involving: P1, P2
Enter the resource ID (e.g., 1 for R1) to release:
```
Once a resource is released, the system attempts to resolve the deadlock automatically and resumes execution.
## Input File Format

Each process is defined by a program block. For example:
```
program P1
resource(1, allocate)
wait(2)
resource(2, allocate)
end

program P2
resource(2, allocate)
wait(1)
resource(1, allocate)
end
```
- or you can use the txt file in this repo
  
## Supported Commands

- **resource(x, allocate)** — Request resource R<x>

- **wait(n)** — Simulate n units of computation time

- **end** — Release all held resources and terminate the process
#Project Structure
```
ps-runner.py      # Main simulation script
program.txt       # Input file defining process actions
README.md         # Project documentation
```
this project is for education, feel free to work on it
