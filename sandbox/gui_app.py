"""Synthetic GUI application for the Build 3 GUI surface.

A small data-entry form (payee, amount, Compute -> total). It is an
instrumented citizen of the boundary, the way real targets would be:
after every change it writes a widget-tree dump (hierarchy, class,
text/value, geometry) and its serialisable state to the control
directory given as argv[1]. State restore (argv[2] = state file) is
how a fork re-enters the app at a checkpoint.
"""
import json, os, sys, tkinter as tk

CTRL = sys.argv[1]
os.makedirs(CTRL, exist_ok=True)
counter = {"n": 0}

def dump(root):
    counter["n"] += 1
    def walk(w):
        node = {"class": w.winfo_class(), "name": str(w).split(".")[-1] or "root",
                "x": w.winfo_x(), "y": w.winfo_y(), "w": w.winfo_width(), "h": w.winfo_height(),
                "children": [walk(c) for c in w.winfo_children()]}
        if isinstance(w, tk.Entry): node["value"] = w.get()
        if isinstance(w, tk.Label): node["text"] = w.cget("text")
        if isinstance(w, tk.Button): node["text"] = w.cget("text")
        return node
    tree = walk(root)
    state = {"payee": payee.get(), "amount": amount.get(), "result": result.cget("text")}
    with open(os.path.join(CTRL, "tree.json"), "w") as f: json.dump({"n": counter["n"], "tree": tree}, f)
    with open(os.path.join(CTRL, "state.json"), "w") as f: json.dump(state, f)

root = tk.Tk(); root.title("LR Form"); root.geometry("320x200")
tk.Label(root, text="Payee").pack()
payee = tk.Entry(root); payee.pack()
tk.Label(root, text="Amount").pack()
amount = tk.Entry(root); amount.pack()
result = tk.Label(root, text="")
def compute():
    try: result.config(text=f"total={int(amount.get()) * 2}")
    except ValueError: result.config(text="total=?")
    dump(root)
tk.Button(root, text="Compute", command=compute).pack()
result.pack()
for widget in (payee, amount):
    widget.bind("<KeyRelease>", lambda e: dump(root))
if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
    state = json.load(open(sys.argv[2]))
    payee.insert(0, state.get("payee", "")); amount.insert(0, state.get("amount", ""))
    result.config(text=state.get("result", ""))
root.after(300, lambda: dump(root))
root.mainloop()
