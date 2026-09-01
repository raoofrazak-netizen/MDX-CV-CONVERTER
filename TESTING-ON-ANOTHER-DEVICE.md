# Testing this build from another device

Two ways to do this, depending on what you actually want to check.

---

## Option A — View the build running on THIS PC, from another device

Use this if you just want to open the portal on your phone/laptop/another
PC and click around — nothing gets installed on the second device, it's
just a browser pointed at this machine over Wi-Fi.

### Step 1 — Start the server so it's reachable on the network

On this PC:

```bash
cd "C:\Users\test\claude converter\MDX CV CONVERTER\app\backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

The `--host 0.0.0.0` part matters — without it, the server only answers to
this PC itself (`localhost`), and no other device can reach it at all.

### Step 2 — Find this PC's network address

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }
```

At the time this doc was written, that address was `172.16.60.157` — it
can change if you reconnect to Wi-Fi or switch networks, so re-run the
command above if the URL below stops working.

### Step 3 — Open it from the other device

Same Wi-Fi network, browser:

```
http://172.16.60.157:8000
```

### If it doesn't load — known blocker on this network

This PC's current Wi-Fi (`#mdxDUBAI`) is classified by Windows as a
**Public** network, and Windows Firewall blocks inbound app connections on
Public networks by default. On top of that, `#mdxDUBAI` looks like a
corporate/campus network, and most of those enable **client/AP isolation**
at the router — a setting that blocks devices from reaching each other
directly, which no amount of Windows firewall configuration can work
around (only network/IT admin control can).

Practical options, roughly in order of effort:

1. **Ask IT** whether client isolation is on for this network, and whether
   it can be disabled for your device — this is the only fix if that's the
   actual blocker.
2. **Switch this PC's network to Private** (requires an administrator
   PowerShell):
   ```powershell
   Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
   New-NetFirewallRule -DisplayName "MDX CV Converter (port 8000)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
   ```
   Won't help if client isolation is the actual cause (see above), and
   changing a shared/corporate network's category is worth checking with
   IT first.
3. **Use a personal hotspot instead** — connect both devices to a phone's
   hotspot rather than the corporate Wi-Fi. Hotspots are almost always
   classified Private automatically and rarely isolate clients, so this
   sidesteps the whole problem without touching any settings on this PC.
4. **Use a tunnelling tool** (e.g. `ngrok`) to expose `localhost:8000` via
   a public HTTPS URL. Works around network isolation entirely, but the
   traffic leaves the local network — fine for a quick look, not something
   to leave running with real staff CVs in it.

---

## Option B — Run a fully independent copy on the other device

Use this if you want the app actually installed and running standalone on
a second machine (its own server, its own copy of the data) — for example,
to hand the build to someone else, or run it somewhere permanent.

### Step 1 — Copy the whole project folder

Everything the app needs is inside `MDX CV CONVERTER` — copy the entire
folder (USB drive, shared drive, zip + transfer, however is easiest) to
the new machine. Nothing outside this folder is required.

### Step 2 — Install Python dependencies

Needs **Python 3.10+** (this build was developed and tested on 3.14) on
the new machine, then:

```bash
cd "MDX CV CONVERTER\app\backend"
pip install -r requirements.txt
```

### Step 3 — Run it

```bash
python -m uvicorn main:app --port 8000
```

Then open `http://localhost:8000` on that same machine. (Add
`--host 0.0.0.0` here too if a *third* device also needs to reach it over
the network — same caveats as Option A apply.)

### What comes along automatically, and what doesn't

| Comes with the folder | Does NOT come with the folder |
|---|---|
| Every CV, photo, and generated document already processed | Python itself, and the packages in `requirements.txt` — `pip install` on the new machine |
| HR-taught heading mappings | The optional AI upgrade's API key (`ANTHROPIC_API_KEY` in `backend/.env`, if that path was ever set up) — a local secret, not stored in the project |
| The auto-approval confidence threshold | The optional local-AI (Ollama) setup — see below |
| The official MDX template, and every code fix made so far | The `impeccable` design skill itself (only its output files — `PRODUCT.md`/`DESIGN.md` — travel; the skill would need reinstalling separately to keep authoring with it) |

Decide deliberately whether the new machine should start with a clean
database or inherit everything already uploaded here — copying the folder
brings real staff CVs with it if any are still in `app/data/`.

### Optional: local AI features on the new machine

The AI-assisted review features (§5h in `HANDOVER.md`) are entirely
optional and the app works fully without them. To enable them on the new
machine too:

1. Install [Ollama](https://ollama.com)
2. `ollama pull llama3.2`
3. Start the server with `AI_PROVIDER=ollama` set:
   ```bash
   AI_PROVIDER=ollama python -m uvicorn main:app --port 8000
   ```

Expect each AI action (Analyze / Verify / Split) to take roughly a minute
per click on CPU-only hardware — this is normal local-model inference
time, not a fault.

---

## After testing

Whichever option you use, `HANDOVER.md` (in the project root) is the
full reference for what the build can and can't do, and `FIXLOG.md` has
the history of every defect found and fixed, in case something you see
looks like a repeat of a known issue.
