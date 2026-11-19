# The SAP Signal

A weekly, verified SAP briefing for SAP leaders and architects, published by hand on LinkedIn.
Phase 1: free, LinkedIn only. Built on the Undercurrent engine (same evidence rules, same approval flow).

**Every week:** the Signal (the change that matters most) · the Architect's Take (from your own notes when
you send them) · five things that moved · the Deadline Radar.

## How it works
```
Sun  discover   a week of SAP news: Google News queries per beat (free) -> clustered events
     triage     buyer impact 0-100: money, deadline, risk, effort (marketing scores low)
     briefing   each story read from a real outlet; every claim needs an exact quote found on the page
     the take   the Signal + a rotating format, written from YOUR notes (Telegram /take, voice, notes/)
     radar      dated changes proposed from verified quotes; code drops any date the quote doesn't state
     linkedin   article page + cover, share post, Thursday story post, Saturday carousel PDF
     draft      email + Telegram: Approve / Reject / Regenerate. Nothing is ever posted for you.
Tue  approve    LinkedIn kit arrives on Telegram; Radar rows filed in deadlines.yaml; notes archived
Thu / Sat       reminders with that day's post
```

## Rules the code enforces
- A claim without an exact quote from the page read is dropped. Sources come from the evidence ledger.
- Vendor-only stories (third-party support, SI marketing, community blogs) are labelled for readers.
- A Radar date must be literally stated in a verified quote, be in the future and not be on the Radar.
- Banned terms (your employer, clients: secret `BANNED_TERMS`) block the Take and block approval.
- The story post never invents a personal anecdote: it uses `voice.md` or leaves a gap for you.

## Commands
`python main.py --help` lists them all: `run`, `scan`, `radar`, `list`, `approve`, `reject`, `remind`,
`collect-notes`, `check-sources`. Setup: see SETUP.md.

## Files you'll edit
- `config.yaml`: name, beats and queries, LinkedIn URLs, models
- `voice.md`: how you sound + real anecdotes
- `deadlines.yaml`: the Radar (fix a date, delete a row, mark `status: passed`)
- `notes/`: your points for next week's Take
