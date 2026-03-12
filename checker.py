import requests
import itertools
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ────────────────────────────────────────────────────────────────────
INPUT_FILE      = "username.txt"
WORKERS         = 100
BATCH_SIZE      = 1000
DEBUG           = False
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

# ── ANSI colours (GitHub Actions supports them) ───────────────────────────────
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
    """Fire a Discord webhook ping for an available username."""
    if not DISCORD_WEBHOOK:
        print(f"{YELLOW}  ⚠  DISCORD_WEBHOOK not set — skipping notification for '{name}'{RESET}", flush=True)
        return
    payload = {
        "content": f"@everyone\nAvailable name: **{name}**",
        "allowed_mentions": {"parse": ["everyone"]},
    }
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code not in (200, 204):
            print(f"{YELLOW}  ⚠  Discord webhook returned {r.status_code} for '{name}'{RESET}", flush=True)
    except Exception as e:
        print(f"{YELLOW}  ⚠  Discord webhook error for '{name}': {e}{RESET}", flush=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    """Check one exact variant. Returns 'TAKEN', 'AVAILABLE', or None (inconclusive)."""
    url = f"https://horizon.meta.com/profile/{variant}/"
    try:
        r = session.get(url, allow_redirects=False, timeout=10)
        loc = r.headers.get("Location", "")

        if DEBUG:
            print(f"{YELLOW}  DEBUG  {variant:20} -> {r.status_code}  {loc}{RESET}", flush=True)

        if r.status_code == 200:
            return "TAKEN"
        if r.status_code in (301, 302):
            if loc == "https://horizon.meta.com/":
                return "AVAILABLE"   # redirected to homepage = username not found
            return "TAKEN"           # redirected to a real profile page
    except Exception:
        pass
    return None  # inconclusive


def check_username(idx, name, total):
    name = name.strip().lstrip("@")
    if not name:
        return idx, name, "SKIP"

    session = requests.Session()

    # Step 1: check exactly as typed
    result = single_check(session, name)
    if result == "TAKEN":
        return idx, name, "TAKEN"
    if result == "AVAILABLE":
        # Exact form is free — verify cap variants too
        for variant in cap_variants(name):
            if variant == name:
                continue
            r = single_check(session, variant)
            if r == "TAKEN":
                return idx, name, "TAKEN"
        return idx, name, "AVAILABLE"

    # Step 2: exact check inconclusive — try cap variants
    for variant in cap_variants(name):
        if variant == name:
            continue
        r = single_check(session, variant)
        if r == "TAKEN":
            return idx, name, "TAKEN"

    return idx, name, "AVAILABLE"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{CYAN}{BOLD}{'=' * 50}{RESET}")
    print(f"{PINK}{BOLD}      💻  M E L L O W 'S  U S E R  F I N D E R  💻{RESET}")
    print(f"{DIM}               made by mellowpluh and leaked by eon,tylosin,and finn{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 50}{RESET}\n")

    if not os.path.exists(INPUT_FILE):
        print(f"{RED}  ✖  '{INPUT_FILE}' not found!{RESET}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        usernames = [l.strip() for l in f if l.strip()]

    total   = len(usernames)
    results = {}
    seen    = set()
    batches = [usernames[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        if len(batches) > 1:
            print(f"{CYAN}{DIM}  ── Batch {batch_num}/{len(batches)} ({len(batch)} usernames) ──{RESET}\n")

        offset = (batch_num - 1) * BATCH_SIZE

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(check_username, offset + idx, name, total): (offset + idx, name)
                for idx, name in enumerate(batch, 1)
                if name.lower() not in seen and not seen.add(name.lower())
            }

            for future in as_completed(futures):
                idx, name, status = future.result()
                results[idx] = (name, status)
                prefix = f"{DIM}[{idx:04}/{total:04}]{RESET} {BOLD}{CYAN}{name:<20}{RESET}"
                if status == "TAKEN":
                    print(f"{prefix}  {random.choice(TAKEN_MESSAGES)}", flush=True)
                elif status == "AVAILABLE":
                    print(f"{prefix}  {random.choice(AVAILABLE_MESSAGES)}", flush=True)
                    send_discord_alert(name)

    taken     = []
    available = []
    for idx in sorted(results):
        name, status = results[idx]
        if status == "TAKEN":
            taken.append(name)
        elif status == "AVAILABLE":
            available.append(name)

    with open("available.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(available))
    with open("taken.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(taken))

    print(f"\n{CYAN}{BOLD}{'=' * 50}{RESET}")
    print(f"{RED}{BOLD}  🔒  TAKEN    : {len(taken)}{RESET}")
    print(f"{GREEN}{BOLD}  💎  AVAILABLE: {len(available)}{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 50}{RESET}\n")


if __name__ == "__main__":
    main()
