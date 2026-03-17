import requests
import itertools
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ────────────────────────────────────────────────────────────────────
INPUT_FILE      = "username.txt"
WORKERS         = 10
DEBUG           = False
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
MAX_RUNTIME     = 5.5 * 60 * 60
START_TIME      = time.time()

# ── ANSI colours ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
PINK   = "\033[95m"
YELLOW = "\033[93m"

TAKEN_MESSAGES = [
    f"{RED}{BOLD}🔒 SNAGGED — already claimed{RESET}",
    f"{RED}{BOLD}💀 DEAD END — someone got there first{RESET}",
    f"{RED}{BOLD}🚫 NO LUCK — this one's taken{RESET}",
    f"{RED}{BOLD}😤 CLAIMED — move on{RESET}",
    f"{RED}{BOLD}🔴 LOCKED IN — not yours{RESET}",
]

AVAILABLE_MESSAGES = [
    f"{GREEN}{BOLD}✅ LET'S GO — it's yours for the taking{RESET}",
    f"{GREEN}{BOLD}💎 CLEAN — nobody has this yet{RESET}",
    f"{GREEN}{BOLD}🟢 OPEN SEASON — grab it{RESET}",
    f"{GREEN}{BOLD}🤑 FREE REAL ESTATE — unclaimed{RESET}",
    f"{GREEN}{BOLD}🚀 ALL YOURS — wide open{RESET}",
]

# ── Discord ───────────────────────────────────────────────────────────────────

def send_discord_alert(name: str):
    if not DISCORD_WEBHOOK:
        print(f"{YELLOW}  ⚠  DISCORD_WEBHOOK not set — skipping '{name}'{RESET}", flush=True)
        return
    payload = {
        "content": f"@everyone\n@everyone Available name: **{name}**",
        "allowed_mentions": {"parse": ["everyone"]},
    }
    for attempt in range(5):
        try:
            r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
            if r.status_code in (200, 204):
                return
            if r.status_code == 429:
                retry_after = float(r.json().get("retry_after", 1))
                time.sleep(retry_after)
                continue
            print(f"{YELLOW}  ⚠  Webhook returned {r.status_code} for '{name}'{RESET}", flush=True)
            return
        except Exception as e:
            print(f"{YELLOW}  ⚠  Webhook error for '{name}': {e}{RESET}", flush=True)
            time.sleep(1)

# ── Check Logic ───────────────────────────────────────────────────────────────

def cap_variants(name: str):
    seen = set()
    seen.add(name)
    yield name
    for v in {name.lower(), name.upper(), name.capitalize()}:
        if v not in seen:
            seen.add(v)
            yield v
    if len(name) <= 6:
        for combo in itertools.product([0, 1], repeat=len(name)):
            v = "".join(c.upper() if combo[i] else c.lower() for i, c in enumerate(name))
            if v not in seen:
                seen.add(v)
                yield v

def single_check(session, variant):
    url = f"https://horizon.meta.com/profile/{variant}/"
    try:
        r = session.get(url, allow_redirects=False, timeout=10)
        loc = r.headers.get("Location", "")
        if DEBUG:
            print(f"{YELLOW}  DEBUG  {variant:20} -> {r.status_code}  {loc}{RESET}", flush=True)
        if r.status_code == 200:
            return "TAKEN"
        if r.status_code in (301, 302):
            if loc.rstrip("/") in ("https://horizon.meta.com", "https://www.meta.com"):
                return "AVAILABLE"
            return "TAKEN"
    except Exception:
        pass
    return None

OCULUS_TOKEN = os.environ.get("OCULUS_TOKEN", "")

def oculus_confirm(name):
    """Secondary confirm via Oculus API — returns True if available, False if taken"""
    try:
        r = requests.get(
            "https://graph.oculus.com/user_checks_by_alias",
            params={
                "alias": name,
                "locale": "en_US",
                "access_token": OCULUS_TOKEN,
            },
            timeout=10
        )
        data = r.json()
        if DEBUG:
            print(f"{YELLOW}  OCULUS  {name} -> {data}{RESET}", flush=True)
        # Taken: error response with code 100
        if "error" in data:
            return False
        # Available: data array with exists=false
        entries = data.get("data", [])
        if entries and entries[0].get("exists") == False:
            return True
        return False  # anything else = treat as taken
    except Exception as e:
        if DEBUG:
            print(f"{YELLOW}  OCULUS ERROR  {name}: {e}{RESET}", flush=True)
        return False  # treat as taken on error

def check_username(idx, name, total):
    name = name.strip().lstrip("@")
    if not name:
        return idx, name, "SKIP"

    time.sleep(1.0)  # rate limit protection

    session = requests.Session()

    # Step 1: Check ALL cap variants on horizon
    for variant in cap_variants(name):
        r = single_check(session, variant)
        if r == "TAKEN":
            return idx, name, "TAKEN"

    # Step 2: Confirm via Oculus API
    if not oculus_confirm(name):
        return idx, name, "TAKEN"

    return idx, name, "AVAILABLE"

# ── Run one pass through the list ─────────────────────────────────────────────

def run_pass(usernames, cycle, total_found):
    total = len(usernames)
    batch = usernames[:]
    random.shuffle(batch)  # different order every cycle

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(check_username, idx, name, total): name
            for idx, name in enumerate(batch, 1)
        }
        for future in as_completed(futures):
            idx, name, status = future.result()
            prefix = f"{DIM}[C{cycle}][{idx:04}/{total:04}]{RESET} {BOLD}{CYAN}{name:<20}{RESET}"
            if status == "TAKEN":
                print(f"{prefix}  {random.choice(TAKEN_MESSAGES)}", flush=True)
            elif status == "AVAILABLE":
                print(f"{prefix}  {random.choice(AVAILABLE_MESSAGES)}", flush=True)
                send_discord_alert(name)
                total_found += 1

    return total_found

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{CYAN}{BOLD}{'=' * 50}{RESET}")
    print(f"{PINK}{BOLD}      💻  M E L L O W 'S  U S E R  F I N D E R  💻{RESET}")
    print(f"{DIM}        24/7 mode — loops username.txt until 5.5hrs{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 50}{RESET}\n")

    if not os.path.exists(INPUT_FILE):
        print(f"{RED}  ✖  '{INPUT_FILE}' not found!{RESET}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        usernames = [l.strip() for l in f if l.strip()]

    print(f"{DIM}  Loaded {len(usernames)} usernames from {INPUT_FILE}{RESET}\n", flush=True)

    total_found = 0
    cycle = 1

    while True:
        elapsed = time.time() - START_TIME
        if elapsed > MAX_RUNTIME:
            print(f"\n{YELLOW}{BOLD}  ⏱  Approaching 6hr limit — stopping cleanly. GitHub Actions will restart.{RESET}\n")
            break

        print(f"\n{CYAN}{DIM}  ── Cycle {cycle} | Elapsed: {int(elapsed // 60)}m | Found so far: {total_found} ──{RESET}\n", flush=True)

        total_found = run_pass(usernames, cycle, total_found)
        cycle += 1

        print(f"\n{DIM}  Cycle done. Restarting in 5 seconds...{RESET}", flush=True)
        time.sleep(5)

    print(f"\n{CYAN}{BOLD}{'=' * 50}{RESET}")
    print(f"{GREEN}{BOLD}  💎  TOTAL AVAILABLE FOUND: {total_found}{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 50}{RESET}\n")


if __name__ == "__main__":
    main()
