# Setup: from zero to your first weekly issue

About 40 minutes. Most of it is the same as Undercurrent, with new names and new secrets.
Nothing here touches Undercurrent: separate repo, bot, approval Worker and secret.

## 0. Gate zero (before anything goes public)
Check your employer's social-media and outside-activity policy. Keep the usual rules: never name the
employer, public sources only. Put the employer's name (and any client names) in the `BANNED_TERMS`
secret (step 5): the pipeline then refuses to approve an issue that contains them.

## 1. Create the repo and unzip (WSL)
On GitHub, create a new **private** repo named `sap-signal` (empty: no README, no .gitignore).
```bash
cd ~
unzip /mnt/c/Users/Sachi/Downloads/sap-signal-v1.zip      # creates ~/sap-signal
cd sap-signal
git init -b main && git add -A && git commit -m "SAP Signal v1"
git remote add origin https://github.com/sachinssoni-GPT/sap-signal.git
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                      # check: all tests pass
```

## 2. A new Telegram bot (2 minutes)
Use a NEW bot, not Undercurrent's: this one also reads your `/take` notes, and keeping them apart means
the two pipelines never consume each other's messages.
@BotFather → `/newbot` → token = `TELEGRAM_BOT_TOKEN`. Send the bot "hi", open
`https://api.telegram.org/bot<TOKEN>/getUpdates`, copy `"chat":{"id": ...}` = `TELEGRAM_CHAT_ID`
(same chat id as Undercurrent's, most likely).

## 3. Local keys
Copy `.env.example` to `.env` and fill it in. You can reuse the OpenAI, Tavily and Gmail values.
Generate a NEW approval secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
set -a; source .env; set +a
python main.py check-sources             # check: search OK, keys present
python main.py scan                      # check: this week's SAP news, by beat (no AI, no cost)
python main.py radar                     # check: the seeded Deadline Radar
```

## 4. Approval Worker (Cloudflare, free)
A fine-grained GitHub token for **only** `sap-signal`, permission **Contents: Read and write**.
```bash
cd approval-worker
npx wrangler secret put APPROVAL_SECRET  # the new value from step 3
npx wrangler secret put GITHUB_TOKEN     # the new fine-grained token
npx wrangler deploy                      # prints https://sap-signal-approval.<you>.workers.dev
cd ..
```
Put that URL in `config.yaml` → `approval.worker_url` (sed, like Undercurrent):
```bash
sed -i 's#https://sap-signal-approval.YOUR-SUBDOMAIN.workers.dev#https://sap-signal-approval.<you>.workers.dev#' config.yaml
```

## 5. GitHub secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
`OPENAI_API_KEY, TAVILY_API_KEY, APPROVAL_SECRET, SMTP_USER, SMTP_PASSWORD, EMAIL_TO,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BANNED_TERMS` (comma-separated, e.g. `EmployerName, ClientName`).

Settings → Actions → General → Workflow permissions → **Read and write permissions**.

## 6. Make it sound like you
Open `voice.md`. Paste 3-5 of your own LinkedIn posts and add real, shareable anecdotes. The Thursday
story post only uses anecdotes listed there; otherwise it leaves a `[YOUR STORY: ...]` gap for you.

## 7. Push and run once
```bash
git add -A && git commit -m "config" && git push -u origin main
```
GitHub → Actions → **Weekly issue (draft for approval)** → Run workflow. In 10-20 minutes you get the
draft by email and Telegram. During the build phase (December), press **Reject** after reading each
dry run; nothing is ever posted for you.

## The weekly rhythm (from January)
| When | What happens | You |
| --- | --- | --- |
| Any day | Message the bot `/take <point>` or a voice note | 2 minutes, optional |
| Mon 18:00 IST | Draft issue built from the week's news + your notes | |
| Mon/Tue | Email + Telegram with Approve / Reject / Regenerate | ~30 min reading |
| Tue (after approving) | Telegram sends the article page, cover, title, share post | ~15 min posting |
| Thu 18:30 IST | Telegram reminder with the story post | fill any [YOUR STORY] gap, post |
| Sat 10:00 IST | Telegram reminder with the carousel PDF + caption | post |

## Creating the LinkedIn newsletter (once)
LinkedIn → turn on Creator Mode if needed → Write article → Create a newsletter (name, description,
weekly). Paste its URL into `config.yaml` → `linkedin.newsletter_url`. From month 2, if you add the free
checklist signup, set `linkedin.signup_url`.
