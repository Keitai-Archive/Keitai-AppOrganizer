import os
import re
import shutil
import sys
import time
import requests
import tkinter as tk
from tkinter import ttk

# 🔐 Your DeepL API key
DEEPL_API_KEY = "YOUR_DEEPL_API_KEY"

# DeepL rate-limit: 1 request/sec
_last_deepl_call = 0.0
DEEPL_MIN_INTERVAL = 1.0

STATUSES = ["Fully-Working", "Not-Working", "Duplicate", "SKIP"]

def extract_app_name(jam_path):
    with open(jam_path, 'r', encoding='shift_jis', errors='ignore') as f:
        for line in f:
            if "AppName" in line:
                m = re.search(r'AppName\s*=\s*(.*)', line)
                if m:
                    return m.group(1).strip()
    return None

def translate_with_deepl(text):
    global _last_deepl_call
    wait = DEEPL_MIN_INTERVAL - (time.time() - _last_deepl_call)
    if wait > 0:
        time.sleep(wait)
    res = requests.post(
        "https://api-free.deepl.com/v2/translate",
        data={"auth_key": DEEPL_API_KEY, "text": text, "source_lang": "JA", "target_lang": "EN"}
    )
    _last_deepl_call = time.time()
    if res.status_code == 200:
        return res.json()['translations'][0]['text']
    return text

def sanitize_folder_name(name):
    return "".join(c if (c.isalnum() or c in " ._-()[]") else "_" for c in name)

def load_existing_apps(parent):
    """[(jam, orig, trans, folder, status), ...]"""
    changelog = os.path.join(parent, "changelog.txt")
    apps = []
    with open(changelog, 'r', encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if not line: continue
            m = re.match(r'^(.*) \((.*)\)$', line)
            if not m: continue
            trans, orig = m.group(1), m.group(2)
            folder = sanitize_folder_name(trans)
            # find status by checking folder location
            status = "SKIP"
            for s in STATUSES[:-1]:
                if os.path.isdir(os.path.join(parent, s, folder)):
                    status = s
                    break
            # detect jam filename inside
            path = os.path.join(parent, status, folder) if status!="SKIP" else os.path.join(parent, folder)
            jam_file = next((f for f in os.listdir(path) if f.lower().endswith('.jam')), "")
            apps.append((jam_file, orig, trans, folder, status))
    return apps

def process_all_jams(parent):
    """[(jam, orig, trans, folder, None), ...]"""
    print("Started Processing Files, please wait... A gui will pop up once ready.");
    jams = [f for f in os.listdir(parent) if f.lower().endswith('.jam')]
    apps = []
    log_path = os.path.join(parent, "changelog.txt")
    for jam in jams:
        orig = extract_app_name(os.path.join(parent, jam))
        if not orig: continue
        trans = translate_with_deepl(orig)
        folder = sanitize_folder_name(trans)
        dest = os.path.join(parent, folder)
        os.makedirs(dest, exist_ok=True)
        base = os.path.splitext(jam)[0]
        for ext in ('.jam','.jar','.sp'):
            src = os.path.join(parent, base+ext)
            if os.path.exists(src):
                shutil.move(src, os.path.join(dest, base+ext))
        # append to old changelog now; we'll rewrite later
        with open(log_path, 'a', encoding='utf-8') as logf:
            logf.write(f"{trans} ({orig})\n")
        apps.append((jam, orig, trans, folder, None))
    return apps

def show_classification_gui(apps):
    root = tk.Tk()
    root.title("Classify Apps")
    root.geometry("600x400")
    frame = ttk.Frame(root); frame.pack(fill="both", expand=True)
    canvas = tk.Canvas(frame)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    scroll = ttk.Frame(canvas)
    scroll.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0,0), window=scroll, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)

    combos = []
    for i, (jam, orig, trans, folder, status) in enumerate(apps):
        lbl = ttk.Label(scroll, text=f"{jam}: {trans} ({orig})")
        lbl.grid(row=i, column=0, sticky="w", padx=5, pady=2)
        cb = ttk.Combobox(scroll, values=STATUSES, state="readonly", width=12)
        # default
        if status in STATUSES:
            cb.current(STATUSES.index(status))
        else:
            cb.current(0)
        cb.grid(row=i, column=1, padx=5, pady=2)
        combos.append((folder, cb))

    def on_ok():
        root.class_map = {f:cb.get() for f,cb in combos}
        root.destroy()
    ttk.Button(root, text="Process", command=on_ok).pack(side="bottom", pady=10)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    root.mainloop()
    return getattr(root, 'class_map', {})

def apply_and_rewrite_log(parent, apps, classification):
    # move folders 
    for jam, orig, trans, folder, _ in apps:
        status = classification.get(folder, "SKIP")

        # find current location
        src = None
        for s in STATUSES[:-1]:  # check the three real statuses
            p = os.path.join(parent, s, folder)
            if os.path.isdir(p):
                src = p
                break
        if src is None:
            root_p = os.path.join(parent, folder)
            if os.path.isdir(root_p):
                src = root_p

        if not src:
            print(f"[WARN] Could not locate {folder}, skipping.")
            continue

        # ensure we always move into a status folder
        dest_root = os.path.join(parent, status)
        os.makedirs(dest_root, exist_ok=True)
        dst = os.path.join(dest_root, folder)
        print(f"[MOVE] {folder} → {status}/")
        shutil.move(src, dst)

    # rewrite changelog sections (unchanged)…
    sections = {s: [] for s in STATUSES[:-1]}
    for jam, orig, trans, folder, _ in apps:
        st = classification.get(folder, "SKIP")
        if st in sections:
            sections[st].append(f"{trans} ({orig})")

    log_path = os.path.join(parent, "changelog.txt")
    with open(log_path, 'w', encoding='utf-8') as f:
        for s in STATUSES[:-1]:
            f.write(f"[{s}]\n")
            for entry in sections[s]:
                f.write(entry + "\n")
            f.write("\n")


if __name__=="__main__":
    if len(sys.argv)!=2:
        print("Usage: python script.py <parent_folder>"); sys.exit(1)
    if DEEPL_API_KEY=="YOUR_DEEPL_API_KEY":
        print("❌ Set your DeepL API key."); sys.exit(1)
    parent = sys.argv[1]
    if not os.path.isdir(parent):
        print("❌ Invalid folder."); sys.exit(1)

    changelog = os.path.join(parent, "changelog.txt")
    if os.path.exists(changelog):
        apps = load_existing_apps(parent)
    else:
        apps = process_all_jams(parent)

    if not apps:
        print("No apps to classify."); sys.exit(0)

    classification = show_classification_gui(apps)
    apply_and_rewrite_log(parent, apps, classification)
    print("Done.")
