# How to run this — in plain steps

> **About the `.py` files:** those are the program's code. You don't open or read
> them. You run **one** of them (the UI) and do everything from your web browser.
> Think of `.py` files like the engine — you just turn the key.

---

## First time only (about 3 minutes)

1. Open the **Terminal** app (Mac: press ⌘+Space, type "Terminal", Enter).
2. Copy-paste this line and press Enter (it moves into the project):
   ```
   cd ~/Desktop/SEO-agents-claude-intelligent-goodall-jw0q9w
   ```
3. Install the requirements (one time):
   ```
   pip install -r requirements.txt
   ```
4. Give the agent its model keys (paste your real values):
   ```
   export AZURE_OPENAI_ENDPOINT="https://…/openai/responses?api-version=2025-04-01-preview"
   export AZURE_OPENAI_API_KEY="your-key"
   ```
   Then open `config.yaml` and set the two deployment names:
   ```
   deployments: {strong: "gpt-5.5", fast: "gpt-4o"}
   ```
   (Optional, makes pages much richer:) `export SEMRUSH_API_KEY="your-key"`

---

## Every time you want to work — start the UI

In Terminal, in the same folder, run:
```
streamlit run ui/app.py
```
Your browser opens at `http://localhost:8501`. **Everything happens here.** That's it.

(Shortcut: double-click **`run_ui.command`** in the project folder instead of typing.)

---

## To CREATE A PAGE (what you were asking)

1. In the browser, pick your brand on the left (or create one).
2. Go to the **▶ Create Page** tab (first tab).
3. Type:
   - **Seed keyword** — e.g. `ai prompt analytics`
   - **Page type** — e.g. `feature`
   - **Target URL** — e.g. `/features/ai-prompt-analytics`
   - **Business context** — one or two sentences on what it is
4. Click **🚀 Generate page**.
5. The agent researches, writes, critiques itself, and shows an
   **Information-Gain score (0–100)**. You can download the result.

## If the agent asks you for data

When no tool can find a number (and you haven't added Semrush), the agent opens
a question in the **Data requests** tab. Answer it (with a source link), then
click **Generate** again. The score climbs as you feed it real data.

## Get keyword data in (no API plan needed)

**Recommended — import your CSV export** (works on any Semrush/Ahrefs plan):
1. In Semrush, export your keyword list to CSV (Keyword Magic / Position Tracking / etc.).
2. In the UI → **Keywords** tab → **Import a keyword export (CSV)** → upload it → **⬆ Import CSV into brain**.
   - It auto-detects the delimiter and the usual columns (Keyword, Search Volume,
     Keyword Difficulty, Intent, CPC, URL) — Semrush, Ahrefs, and GSC exports all work.
3. Re-upload a fresh export whenever you pull new data. That's it — the agent now
   reads volumes/difficulty from the brain and stops asking you for them.

**Optional — live API** (only if your plan includes API access): sidebar →
**🔑 API keys** → paste `SEMRUSH_API_KEY` → **Apply** → **Test Semrush**, then use
**⬇ Pull from Semrush** in the Keywords tab. Keys stay in session memory, never on disk.

## To make the brand smarter (better pages)

Fill these tabs once and every future page benefits:
- **Brand** — author name/title/credentials (Google rewards this).
- **Facts** — your real numbers; tick **"original data"** for your own benchmarks.
- **Keywords** — terms + target URLs.
- **Site structure** — your pages, so the agent links internally.
- **Brand files** — paste your product docs / case studies.

---

## What the score means

- **70+** = information-rich, the kind Google rewards. The gate is **enforced**,
  so a page under 70 is sent back to be improved, not shipped.
- A thin page (lots of words, no citations/data/examples) scores low on purpose.
- Full definition: `docs/GOAL-information-gain-metrics.md`.
