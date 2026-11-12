"""
teams_agent_ollama.py - Free, local agent that fixes new Microsoft Teams issues.

Setup (Windows, same folder as fix-teams.ps1):
    1. Install Ollama from https://ollama.com
    2. ollama pull llama3.1:8b        (or qwen2.5:7b - any model that supports tools)
    3. pip install ollama
    4. python teams_agent_ollama.py "Teams is stuck on a white screen"

Safety (enforced in code, not just in the prompt, because small models can slip):
  - Only four tools. No free-form shell.
  - Level 2 is blocked until Level 1 has run, and needs your typed "yes".
  - Chats are never touched: the script only handles the local cache folder.
  - Every step is logged to agent_trail.txt and teams_fix_log.txt.
"""
import json
import pathlib
import subprocess
import sys
from datetime import datetime

import ollama

BASE = pathlib.Path(__file__).parent
SCRIPT = BASE / "fix-teams.ps1"
SCRIPT_LOG = BASE / "teams_fix_log.txt"
TRAIL = BASE / "agent_trail.txt"
MODEL = "llama3.1:8b"
MAX_TURNS = 12

state = {"level1_done": False, "level2_done": False,
         "asked_after_fix": False, "resolved": False}


def next_step_hint() -> str:
    """Deterministic next step, used to nudge a model that forgot to call a tool."""
    if not state["level1_done"]:
        return "Call the run_fix tool with level 1 now."
    if not state["asked_after_fix"]:
        return "Call the ask_user tool to ask whether the issue is resolved."
    if not state["level2_done"]:
        return "The issue is not resolved. Call the run_fix tool with level 2 now."
    return "Give your final short summary."

SYSTEM_PROMPT = """You are a careful IT support agent for NEW Microsoft Teams on Windows.

GOAL: Teams is open and working, and no chat messages are lost or sent.

SCOPE: Use only your tools. You cannot see the Teams window, so ask the user
whether the problem is fixed after each fix attempt.

PROCEDURE (follow in this exact order):
1. Call check_teams_status.
2. Call run_fix with level 1. Then call ask_user: is the issue resolved?
3. Only if NOT resolved, call run_fix with level 2 (the user must confirm).
   Then call ask_user again.
4. If still not resolved, stop. Tell the user to repair the app in
   Settings > Apps > Installed apps > Microsoft Teams > Advanced options > Repair.

STANDARD: Never do anything that could touch, delete, edit or send chats.
If a tool returns an error or BLOCKED, stop and report it. Do not improvise.

REPORTING: Each turn, briefly say what you inspected, decided, and are unsure
about. End with a short summary of what was tried and the outcome."""

TOOLS = [
    {"type": "function", "function": {
        "name": "check_teams_status",
        "description": "Check whether new Teams is running and whether its cache folder exists. Read-only.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "run_fix",
        "description": "Run the fix script. level 1 = close Teams, wait, reopen. level 2 = close Teams, back up the cache, reopen.",
        "parameters": {"type": "object",
                       "properties": {"level": {"type": "integer", "description": "1 or 2"}},
                       "required": ["level"]}}},
    {"type": "function", "function": {
        "name": "read_fix_log",
        "description": "Read the last 30 lines of the fix script's log.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "ask_user",
        "description": "Ask the user a short question and get their typed answer.",
        "parameters": {"type": "object",
                       "properties": {"question": {"type": "string"}},
                       "required": ["question"]}}},
]


def trail(text: str) -> None:
    with open(TRAIL, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")


def check_teams_status() -> str:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ms-teams.exe"],
                         capture_output=True, text=True).stdout
    cache = pathlib.Path.home() / "AppData/Local/Packages/MSTeams_8wekyb3d8bbwe/LocalCache/Microsoft/MSTeams"
    return json.dumps({"teams_running": "ms-teams.exe" in out,
                       "cache_folder_exists": cache.exists(),
                       "level1_already_tried": state["level1_done"]})


def run_fix(level) -> str:
    try:
        level = int(level)
    except (TypeError, ValueError):
        return "ERROR: level must be 1 or 2."
    if level not in (1, 2):
        return "ERROR: level must be 1 or 2."
    if level == 2:
        if not state["level1_done"]:
            return "BLOCKED: run level 1 first."
        ok = input("\nAgent wants to run LEVEL 2 (back up + clear Teams cache, then reopen). Chats are not affected. Proceed? (yes/no): ")
        if ok.strip().lower() != "yes":
            return "BLOCKED: user declined level 2."
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(SCRIPT), "-Level", str(level)],
                       capture_output=True, text=True)
    state["level1_done" if level == 1 else "level2_done"] = True
    state["asked_after_fix"] = False
    return f"exit_code={r.returncode}\n{(r.stdout or '')[-1500:]}\n{(r.stderr or '')[-500:]}"


def read_fix_log() -> str:
    if not SCRIPT_LOG.exists():
        return "No log yet."
    return "\n".join(SCRIPT_LOG.read_text(encoding="utf-8").splitlines()[-30:])


def ask_user(question: str) -> str:
    answer = input(f"\nAgent asks: {question}\n> ")
    state["asked_after_fix"] = True
    state["resolved"] = answer.strip().lower().startswith(("y", "fixed", "resolved", "working"))
    return answer


HANDLERS = {
    "check_teams_status": lambda a: check_teams_status(),
    "run_fix": lambda a: run_fix(a.get("level")),
    "read_fix_log": lambda a: read_fix_log(),
    "ask_user": lambda a: ask_user(a.get("question", "Is the issue resolved?")),
}


def main() -> None:
    if not SCRIPT.exists():
        sys.exit("fix-teams.ps1 must be in the same folder as this script.")
    problem = " ".join(sys.argv[1:]) or input("Describe the Teams problem: ")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Problem reported: {problem}"},
    ]
    trail(f"=== NEW RUN. Model: {MODEL}. Problem: {problem}")

    nudges = 0
    for _ in range(MAX_TURNS):
        resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS,
                           options={"temperature": 0})
        msg = resp.message
        messages.append(msg)

        if msg.content and msg.content.strip():
            print(f"\nAgent: {msg.content}")
            trail(f"AGENT SAID: {msg.content}")

        if not msg.tool_calls:
            finished = (state["asked_after_fix"]
                        and (state["resolved"] or state["level2_done"]))
            if finished or nudges >= 3:
                trail("=== RUN ENDED")
                return
            # Model described a tool call in text instead of making one. Nudge it.
            nudges += 1
            hint = next_step_hint()
            trail(f"NUDGE {nudges}: no tool call made. Hint: {hint}")
            messages.append({"role": "user", "content":
                "You wrote text but did not make a real tool call. Do not write "
                "JSON or describe the call. Use the tool-calling interface. " + hint})
            continue

        nudges = 0  # a real tool call happened, so reset the nudge budget
        for call in msg.tool_calls:
            name, args = call.function.name, dict(call.function.arguments or {})
            trail(f"TOOL CALL: {name} {json.dumps(args)}")
            handler = HANDLERS.get(name)
            try:
                output = handler(args) if handler else f"ERROR: unknown tool '{name}'."
            except Exception as e:
                output = f"TOOL ERROR: {e}"
            trail(f"TOOL RESULT: {output[:500]}")
            messages.append({"role": "tool", "tool_name": name, "content": output})

    trail("=== STOPPED: hit max turns")
    print("\nStopped: reached the maximum number of steps.")


if __name__ == "__main__":
    main()