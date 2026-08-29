# Setup: Anthropic API key

The MDX Faculty CV Converter uses Claude (Anthropic) to classify CV content
into the correct sections. Without an API key, uploads will extract text
successfully but fail at the AI classification step with a clear error —
the app won't crash or fabricate results, it just can't do the AI part yet.

## 1. Get a key

1. Go to **[console.anthropic.com](https://console.anthropic.com)** and sign
   in (or create an account).
   - **Recommendation:** if Middlesex already has, or is setting up, an
     organizational Anthropic account, request a key under that org rather
     than a personal account — this is going into a real HR system, and
     billing/ownership shouldn't be tied to one individual.
2. Go to **Settings → API Keys** ([console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)).
3. Click **Create Key**, name it something identifiable like
   `mdx-cv-converter`, and copy the value — it starts with `sk-ant-...` and
   is shown only once.
4. Go to **Settings → Billing** and make sure billing is set up. This is a
   separate, pay-as-you-go product from any existing Claude.ai subscription
   — API calls won't work until billing is active. Expected usage is low at
   Phase 1 pilot volume (see the build brief's volume assumptions).

## 2. Add the key to the app

Open this file in a text editor:

```
C:\Users\r.razak\Claude projects\MDX CV CONVERTER\app\backend\.env
```

Replace the empty key line with your real key:

```
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
ANTHROPIC_MODEL=claude-sonnet-4-5
```

Save the file. Do not commit or share this file — it contains a live
credential. `.env` should stay out of version control if this project is
ever put under git.

## 3. Restart the server

If the server is already running, it needs to be restarted to pick up the
new key (it's loaded once at startup). Ask me to restart it once the key is
in place, and I'll run a real CV through the full pipeline to confirm
classification is actually working.
