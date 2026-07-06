# Getting Started — run the NTT Pricing Tool on your PC

A short, non-technical guide. You do this **once**; after that it's a
double-click.

## 1. Install Python (one time)
- Go to <https://www.python.org/downloads/> and install **Python 3.10 or newer**.
- On Windows, on the first install screen **tick “Add Python to PATH”**, then
  click Install.

## 2. Get the tool onto your PC

Pick one. **Option A updates itself; Option B is a fixed snapshot.**

### Option A — clone it (recommended: updates come automatically)
- Install **GitHub Desktop** from <https://desktop.github.com/> (or Git for
  Windows) — one time.
- Clone `alytawakol92-dev/ntt-pricing-tool`, and switch to the branch
  **`claude/quotation-panel-design-tool-moy141`** (top of GitHub Desktop →
  Current Branch → pick it).
- From then on, every time you double-click `run.bat` it **pulls the latest
  version automatically** before starting.

### Option B — download ZIP (simple, but no auto-updates)
- On GitHub, branch `claude/quotation-panel-design-tool-moy141` → green
  **Code** button → **Download ZIP** → **extract** to e.g.
  `Documents\NTT-Pricing-Tool`.
- To get a newer version later you must download the ZIP again and replace the
  folder. (A downloaded copy does **not** update by itself.)

## 3. Start it
- **Windows:** double-click **`run.bat`**.
- **Mac/Linux:** open a terminal in the folder and run **`./run.sh`**.

The first launch takes a minute or two (it sets itself up). After that a
browser window opens automatically at **http://127.0.0.1:5000**.

## 4. Use it
On the page:
1. Upload your **single line diagram** — `.dwg`, `.dxf`, `.pdf` or `.json`.
2. Upload your **Schneider price book** — the multi-tab Excel (`.xlsx`).
3. (Optional) upload a **load schedule** and a **pricing config**.
4. Fill in the project details and press **Generate quotation**.
5. Open / download the **Technical** and **Commercial** offers.

To stop the tool, close the black command window (Windows) or press
**Ctrl+C** in the terminal.

---

### Notes
- **DXF, PDF and JSON** diagrams work out of the box.
- **DWG** files need a free converter. Easiest on Windows: install the **ODA
  File Converter** (opendesign.com), then set an environment variable
  `NTT_DWG2DXF` to its path — or simply **export the drawing to DXF** from
  AutoCAD, which needs nothing extra.
- Nothing you upload leaves your PC — it all runs locally.
- To share it on your office network, start it with
  `python -m ntt_pricing.web --host 0.0.0.0` and open
  `http://<your-PC-IP>:5000` from another machine.
