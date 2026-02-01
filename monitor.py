import os
import re
import sys
import time
from datetime import datetime

def get_steam_path_windows():
    try:
        import winreg
    except ImportError:
        return None

    for hive, subkey, value in [
        ("HKCU", r"Software\Valve\Steam", "SteamPath"),
        ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ("HKLM", r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]:
        try:
            root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            with winreg.OpenKey(root, subkey) as k:
                v, _ = winreg.QueryValueEx(k, value)
                if v and os.path.isdir(v):
                    return os.path.normpath(v)
        except OSError:
            pass
    return None

def parse_libraryfolders_vdf(vdf_path):
    if not os.path.isfile(vdf_path):
        return []
    text = open(vdf_path, "r", encoding="utf-8", errors="ignore").read()
    paths = re.findall(r'"path"\s*"([^"]+)"', text)
    if paths:
        return [os.path.normpath(p.replace("\\\\", "\\")) for p in paths if p]
    paths = re.findall(r'"\d+"\s*"([A-Za-z]:\\\\[^"]+)"', text)
    return [os.path.normpath(p.replace("\\\\", "\\")) for p in paths if p]

def get_libraries(steam_root):
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    libs = [steam_root] + parse_libraryfolders_vdf(vdf)
    libs = [p for p in libs if os.path.isdir(p)]
    out, seen = [], set()
    for p in libs:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out

def appid_to_name(appid, libraries):
    pat = f"appmanifest_{appid}.acf"
    for lib in libraries:
        acf = os.path.join(lib, "steamapps", pat)
        if os.path.isfile(acf):
            txt = open(acf, "r", encoding="utf-8", errors="ignore").read()
            m = re.search(r'"name"\s*"([^"]+)"', txt)
            if m:
                return m.group(1)
    return f"AppID {appid}"

RE_APP_UPDATE = re.compile(
    r'^\[(?P<ts>[\d-]+\s+[\d:]+)\]\s+AppID\s+(?P<appid>\d+)\s+App update changed\s*:\s*(?P<flags>.*)$'
)
RE_STATE = re.compile(
    r'^\[(?P<ts>[\d-]+\s+[\d:]+)\]\s+AppID\s+(?P<appid>\d+)\s+state changed\s*:\s*(?P<flags>.*)$'
)
RE_PROGRESS = re.compile(
    r'^\[(?P<ts>[\d-]+\s+[\d:]+)\]\s+AppID\s+(?P<appid>\d+)\s+update started\s*:\s*download\s+(?P<done>\d+)/(?P<total>\d+)'
)
RE_RATE = re.compile(
    r'^\[(?P<ts>[\d-]+\s+[\d:]+)\]\s+Current download rate:\s+(?P<mbps>[0-9.]+)\s+Mbps'
)
RE_CANCELED = re.compile(
    r'^\[(?P<ts>[\d-]+\s+[\d:]+)\]\s+AppID\s+(?P<appid>\d+)\s+update canceled\s*:\s*(?P<reason>.*)$'
)
RE_FINISHED = re.compile(
    r'^\[(?P<ts>[\d-]+\s+[\d:]+)\]\s+AppID\s+(?P<appid>\d+)\s+finished update\b'
)

def tail_lines(path, n=500, max_bytes=600_000):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes), os.SEEK_SET)
        data = f.read()
    lines = data.decode("utf-8", errors="ignore").splitlines()
    return lines[-n:]

def pick_active_app(lines):
    latest = None
    for i, line in enumerate(lines):
        m = RE_APP_UPDATE.match(line)
        if not m:
            continue
        flags = m.group("flags")
        if ("Downloading" in flags) or ("Running Update" in flags):
            latest = (i, int(m.group("appid")), flags.strip())
    return latest[1] if latest else None

def is_finished_for_app(appid, lines):
    for line in lines:
        m = RE_FINISHED.match(line)
        if m and int(m.group("appid")) == appid:
            return True
    return False

def summarize_for_app(appid, lines):
    flags_app_update = None
    flags_state = None
    done = total = None
    rate_mbps = None
    canceled_reason = None

    for line in lines:
        m = RE_APP_UPDATE.match(line)
        if m and int(m.group("appid")) == appid:
            flags_app_update = m.group("flags").strip()

        m = RE_STATE.match(line)
        if m and int(m.group("appid")) == appid:
            flags_state = m.group("flags").strip()

        m = RE_PROGRESS.match(line)
        if m and int(m.group("appid")) == appid:
            done = int(m.group("done"))
            total = int(m.group("total"))

        m = RE_CANCELED.match(line)
        if m and int(m.group("appid")) == appid:
            canceled_reason = m.group("reason").strip()

        m = RE_RATE.match(line)
        if m:
            rate_mbps = float(m.group("mbps"))

    combined = " ".join([f for f in [flags_app_update, flags_state, canceled_reason] if f]).lower()

    if "downloading" in combined:
        status = "DOWNLOADING"
    elif any(x in combined for x in ["suspended", "paused", "stopping", "disabled"]):
        status = "PAUSED"
    elif "running update" in combined:
        status = "RUNNING_UPDATE"
    else:
        status = "IDLE"

    # Приоритет по скорости
    if rate_mbps is not None:
        if rate_mbps > 0:
            status = "DOWNLOADING"
        elif rate_mbps == 0.0 and status in ("DOWNLOADING", "RUNNING_UPDATE"):
            status = "PAUSED"

    return {"done": done, "total": total, "rate_mbps": rate_mbps, "status": status}

def mbps_to_mbs(mbps):
    return mbps / 8.0

def main():
    steam = get_steam_path_windows()
    if not steam:
        print("ERROR: Steam not found in registry")
        sys.exit(1)

    content_log = os.path.join(steam, "logs", "content_log.txt")
    if not os.path.isfile(content_log):
        print("ERROR: content_log.txt not found:", content_log)
        sys.exit(1)

    libraries = get_libraries(steam)

    idle_streak = 0

    done_mode = False
    done_name = None

    for minute in range(1, 6):
        ts = datetime.now().strftime("%H:%M:%S")

        # Если уже завершили — просто печатаем DONE до конца 5 минут
        if done_mode:
            print(f"[{ts}] {minute}/5  {done_name} | DONE | 0.00 MB/s (0.000 Mbps) | progress: finished")
            time.sleep(60)
            continue

        lines = tail_lines(content_log, n=800)
        appid = pick_active_app(lines)

        if not appid:
            idle_streak += 1
            print(f"[{ts}] {minute}/5  No active Steam download/update detected")
            if idle_streak >= 2:
                done_mode = True
                done_name = "Steam"
            time.sleep(60)
            continue

        info = summarize_for_app(appid, lines)
        name = appid_to_name(appid, libraries)

        if info["rate_mbps"] is None:
            speed = "unknown"
        else:
            speed = f"{mbps_to_mbs(info['rate_mbps']):.2f} MB/s ({info['rate_mbps']:.3f} Mbps)"

        if info["done"] is not None and info["total"]:
            pct = info["done"] / info["total"] * 100
            prog = f"{pct:.1f}% ({info['done']}/{info['total']} bytes)"
        else:
            prog = "progress: unknown"

        print(f"[{ts}] {minute}/5  {name} | {info['status']} | {speed} | {prog}")

        # Если Steam сообщил, что обновление закончено — включаем DONE-режим (без выхода)
        if is_finished_for_app(appid, lines):
            done_mode = True
            done_name = name

        # IDLE 2 минуты подряд - DONE-режим
        if info["status"] == "IDLE":
            idle_streak += 1
            if idle_streak >= 2:
                done_mode = True
                done_name = name
        else:
            idle_streak = 0

        time.sleep(60)

if __name__ == "__main__":
    main()
