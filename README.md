# Proofhunt

**Find the proof. Then write the email.**

Proofhunt finds small agencies that show **real proof of a problem you can fix**, picks the right person, and drafts a short email that quotes that proof. You review the drafts. Proofhunt sends them from your own Gmail, follows up, and stops when someone replies.

- Free and open source (MIT). Self-hosted. Your data stays in your own Supabase project.
- One user per install. You bring your own API keys.
- Every claim in an email points to a **real quote** from the company's own website. No quote, no claim.

> **Cost note.** Proofhunt itself is free. The services it calls are not always free: Firecrawl (reads websites), DeepSeek (the AI model), and a server if you host it. All three have free or cheap tiers. Proofhunt shows your credit use on the **Usage & credits** page and stops a run when a budget you set is reached.

---

## How it works

```
Your CV ─► Offer map ─► Campaign ─► Discovery ─► Audit ─► Filters ─► Contact ─► Judge ─► Assets ─► Emails ─► Review ─► Send ─► Track
```

1. **CV → offer map.** Upload a CV (PDF, DOCX, TXT). The AI turns it into an *offer map*: the services you sell, the problems they solve, and **signals** to look for on a prospect's site (a phrase, a missing tool, a tool in use, a hiring ad, or an AI check). You can edit all of it.
2. **Campaign.** Pick countries, company size, job titles and keywords. The form shows the Firecrawl credit cost before you start.
3. **Discovery.** Firecrawl search finds agency websites. Directory and list sites are dropped. Each domain is cleaned and de-duplicated.
4. **Audit.** Proofhunt reads up to 4 pages per company (home, about, contact, careers/services). Pages are saved and never fetched twice.
5. **Extract and verify.** Code checks and the AI pull out facts. **Every quote is checked against the saved page text.** A quote that is not on the page is thrown away.
6. **Filters.** Companies that do not match your campaign are dropped, with the proof (for example "250 full-time specialists").
7. **Contact pick.** Proofhunt picks the right person from the site. It uses **only emails published on the company's own website**. It never guesses an address. If a site lists nobody, the company is marked `no_contact`.
8. **Judge.** The AI scores the fit from 0 to 100. Hard rules cap the score if it cannot cite valid evidence.
9. **Assets.** Every qualified lead gets a short audit report with a private link. The best leads also get a demo project spec.
10. **Email sequence.** One main email and 3 follow-ups per lead. Code checks reject drafts that are too long, have more than one link, use spam phrases or leave placeholders.
11. **Review queue.** You read, edit, approve or skip (keyboard: `A` `E` `R` `S` `J` `K`). Auto-send is off by default.
12. **Sending engine.** Sends through your Gmail inside a daily cap, a warm-up ramp, random gaps, and a send window in the *lead's* time zone, Monday to Friday.
13. **Tracking.** Replies and bounces are found automatically. A reply stops the sequence. "No" or "unsubscribe" adds the address to the do-not-contact list forever.
14. **Stats.** The dashboard shows the funnel and reply rates per offer, signal, country, size and score band. Use the top signals to improve your offer map.

### Safety rules built in

- Emails go only to addresses published on the company's site. The source page URL is stored.
- Every email has your real name, your postal address and a clear way to opt out. **Real sending is blocked until you set a sender name and postal address.**
- Opt-outs and bounces are blocked at once and for good. More than 3 bounces in 24 hours pauses sending by itself.
- No tracking pixels. No link trackers.
- `DRY_RUN=true` is the default: the full flow runs but nothing is sent.
- You are responsible for following the email laws where you and your recipients live (CAN-SPAM, GDPR/PECR, CASL, Spam Act). The defaults are cautious. They are not legal advice.

---

## What you need

| Thing | Why | Cost |
|---|---|---|
| Docker + Docker Compose | Runs the app | Free |
| [Supabase](https://supabase.com) project | Database and CV storage | Free tier is enough |
| [Firecrawl](https://firecrawl.dev) API key | Search and read websites | Free credits, then paid |
| [DeepSeek](https://platform.deepseek.com) API key | The AI model | Pay per use, cheap |
| Google Cloud project (free) | Lets Proofhunt use **your** Gmail | Free |

---

## Install on your computer

### 1. Get the code

```bash
git clone https://github.com/nazmulhasanrupom/proofhunt.git
cd proofhunt
cp .env.example .env
```

### 2. Set up Supabase

1. Create a project at supabase.com.
2. Open **SQL Editor**. Paste and run `backend/migrations/001_init.sql`. Then run `backend/migrations/002_firecrawl_balance.sql`.
3. Open **Project Settings → API**. Copy the **Project URL** and the **service_role** key.
   The `service_role` key has full database access. It goes only in `.env` on your server. Never put it in a browser or a public place.

The private storage bucket `cvs` is created for you on first start.

### 3. Fill in `.env`

| Variable | Value |
|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | From step 2 |
| `DEEPSEEK_API_KEY` | From your DeepSeek account |
| `FIRECRAWL_API_KEY` | From your Firecrawl account |
| `APP_SECRET_KEY` | A key that encrypts your Gmail login. Make one: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From step 4 (can wait until you want to send) |
| `DRY_RUN` | Keep `true` until you finish the test send |
| `DEV_FIRECRAWL_CREDIT_LIMIT`, `DEV_LLM_CALL_LIMIT` | Safety stops for testing (150 credits, 100 calls, **all-time**). Leave the value empty for no limit |

### 4. Set up Google (to send from your Gmail)

You can skip this to try everything in dry-run mode.

1. [Google Cloud Console](https://console.cloud.google.com): create a project. Enable the **Gmail API**.
2. **OAuth consent screen:** User type *External*. Add your Gmail as a **test user**. Add scopes `gmail.send` and `gmail.readonly`.
3. **Credentials → Create credentials → OAuth client ID → Web application.**
   Authorized redirect URI: `http://localhost:8000/auth/google/callback`
4. Copy the client ID and secret into `.env`.

Status *Testing* means your Gmail login expires after 7 days. Press **Reconnect Gmail** in Settings. Status *In production* shows an "unverified app" screen. Click **Advanced**, then continue.

### 5. Start

```bash
docker compose up -d --build
```

Open **http://localhost:5173**. Check http://localhost:8000/health. It should say `"db":"ok"`.

### 6. First steps in the app

1. **Settings:** enter sender name, title and postal address. Press **Connect Gmail**. Enter your Firecrawl starting balance.
2. **Profile & CV:** upload your CV. Press **Generate offer map**. Read it and edit it.
3. **Campaigns → New campaign.** Start with a **small** one: `maxCompaniesToScan = 3`. Press start.
4. **Activity** shows the live log. **Companies** and **Leads** show the results. Open any row to see the quotes behind it.
5. **Review queue:** read the drafts. Approve or skip.

### 7. First real send (test it on yourself)

1. Settings → **Create test lead**. It makes a lead that emails *your own* address.
2. Review queue → approve it.
3. Set `DRY_RUN=false` in `.env`. Run `docker compose up -d`. Wait up to 4 minutes. Check your inbox and the **Outbox** page.
4. Reply to it from *another* account. Within 10 minutes the **Replies** page shows it and the sequence stops.
5. Set `DRY_RUN=true` again if you want to stay in test mode.

### Before real use

- `DRY_RUN=false`.
- Clear `DEV_FIRECRAWL_CREDIT_LIMIT` and `DEV_LLM_CALL_LIMIT` (empty values). Otherwise runs stop at 150 credits and 100 AI calls.
- Keep the review queue on for your first 50 leads.
- Start with a low daily cap and keep **warm-up** on (10 a day, +5 each week, up to your cap, maximum 50).

---

## Install on Coolify (or any server)

Proofhunt is 4 containers: `web`, `api`, `worker`, `redis`. Only `web` is public. It forwards `/api` to the API, so you need **one domain** and no extra setup for CORS.

> Supabase and GitHub do not run the app. Supabase holds the data. Run the containers on [Coolify](https://coolify.io), a VPS, or any Docker host.

1. Do **steps 2 and 4** above (Supabase and Google). In Google, use the redirect URI `https://YOUR-DOMAIN/api/auth/google/callback`.
2. In Coolify: **New resource → Public/Private Repository → this repo**. Build pack: **Docker Compose**. Compose file: `docker-compose.coolify.yml`.
3. Set the domain of the **`web`** service to `https://YOUR-DOMAIN:80` (the `:80` is the port inside the container).
4. Add these environment variables in Coolify:

   | Variable | Value |
   |---|---|
   | `ACCESS_PASSWORD` | **Required.** A long password. Anyone with the URL could otherwise read your leads and send email as you |
   | `FRONTEND_URL` | `https://YOUR-DOMAIN` |
   | `PUBLIC_BASE_URL` | `https://YOUR-DOMAIN` (used for the report links in emails) |
   | `GOOGLE_REDIRECT_URI` | `https://YOUR-DOMAIN/api/auth/google/callback` |
   | `SUPABASE_URL`, `SUPABASE_KEY`, `DEEPSEEK_API_KEY`, `FIRECRAWL_API_KEY`, `APP_SECRET_KEY` | Required |
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | To send email |
   | `DRY_RUN` | `true` until you finish the test send |

5. Deploy. Open `https://YOUR-DOMAIN`. Sign in with your password.
6. Keep **one** worker. Two workers would send emails twice.

Open to the internet without a password: `/api/health` (status only) and `/r/{token}` (the report page you link in emails). Everything else needs the password. After 20 wrong passwords in 15 minutes, further tries are blocked.

The same thing works on any host:
`docker compose -f docker-compose.coolify.yml --env-file .env up -d --build` behind your own HTTPS proxy.

---

## Pages

| Page | What it does |
|---|---|
| Dashboard | Qualified leads, sent this week, reply rate, credits left, funnel, top signals, hot replies |
| Activity / Runs | Live log of a run. Pause, resume, cancel |
| Profile & CV / Offer map | Upload a CV. Edit services, problems, proof and signals |
| Campaigns | Filters and the credit estimate |
| Companies | Every company with facts, quotes, people and the judgment |
| Leads | Board (drag to change stage) or table. Emails, report, demo, notes |
| Review queue | Approve, edit, regenerate or skip drafts |
| Outbox / Replies | What is scheduled and sent. Replies with a label (interested, not now, …) |
| Usage & credits | Credits, tokens and emails per day. Cost per qualified lead |
| Do not contact | Block an email or a whole domain |
| Settings | Gmail, sender info, limits, send window, follow-up days |

`Ctrl+K` jumps to any page, company or lead.

---

## Settings that matter

- **Daily cap:** max 50. **Warm-up:** 10 a day, +5 for each full week since the first real send.
- **Send window:** default 09:00–16:30 in the lead's time zone, Monday to Friday.
- **Gap:** random 3 to 9 minutes between emails.
- **Follow-ups:** after 3, 4 and 7 business days.
- **Qualify score:** 70 and up qualifies. 50 to 69 is "maybe". 85 and up also gets a demo spec.

---

## Tests

```bash
docker compose exec api sh -c "pip install -q pytest && python -m pytest -q tests"
```

20 tests. They never call a live service.

## If something goes wrong

| Problem | Fix |
|---|---|
| `/health` shows `db: error` | Check `SUPABASE_URL` and `SUPABASE_KEY`. Check you ran both migrations |
| A run stopped | Runs → open it → **Resume**. A worker restart pauses running runs on purpose |
| "Budget stop" in the log | You hit a limit. Raise or clear it in `.env`, then Resume |
| "Reconnect Gmail" | Settings → Reconnect Gmail (Google test mode expires every 7 days) |
| Message is `failed` | Look in the Gmail *Sent* folder first, then press Retry in Outbox |
| Gmail login unreadable | `APP_SECRET_KEY` changed. Reconnect Gmail |
| Sending blocked | Settings: add sender name and postal address, and connect Gmail |
| Blank or broken page | Open the browser console and report the error. Pages show an error box, not a black screen |

## Project layout

```
backend/    FastAPI API, arq worker, pipeline, sending engine, migrations, tests
frontend/   React + Vite + Tailwind web app (nginx in Docker)
docker-compose.yml          local
docker-compose.coolify.yml  hosting
```

Stack: Python 3.12, FastAPI, arq + Redis, Supabase (Postgres + Storage), Firecrawl v2, DeepSeek (OpenAI-compatible API), Gmail API, React, TypeScript, Tailwind, TanStack Query.

## License

MIT. See [LICENSE](LICENSE). Use it, change it, share it.
