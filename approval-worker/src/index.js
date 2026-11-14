// SAP Signal approval Worker (a separate copy from Undercurrent's: its own name, repo and secrets).
// The email/Telegram buttons open GET /decide?action=..&date=..&exp=..&sig=..
// GET only shows a confirmation page (link scanners and previews cannot trigger anything).
// POST verifies the HMAC signature + expiry, then fires a GitHub repository_dispatch event,
// which runs .github/workflows/decide.yml (or weekly-issue.yml for "regenerate").

const ACTIONS = {
  approve: { event: "sig-approve", label: "Approve this issue", color: "#1f7a3a" },
  reject: { event: "sig-reject", label: "Reject this issue", color: "#a62b2b" },
  regenerate: { event: "sig-regenerate", label: "Discard and regenerate", color: "#555" },
  run: { event: "sig-run", label: "Build a new draft now", color: "#0b6e69" },
  notes: { event: "sig-notes", label: "Collect my notes now", color: "#0b6e69" },
};

const enc = new TextEncoder();

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function verify(env, p) {
  if (!ACTIONS[p.action]) return "Unknown action.";
  if (!/^\d{4}-\d{2}-\d{2}(-[1-9]\d?)?$/.test(p.date || "")) return "Bad edition id.";
  const exp = Number(p.exp);
  if (!Number.isFinite(exp) || Date.now() / 1000 > exp) return "This link has expired.";
  const expected = await hmacHex(env.APPROVAL_SECRET, `${p.action}:${p.date}:${exp}`);
  return safeEqual(expected, p.sig || "") ? null : "Invalid signature.";
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function page(title, inner, status = 200) {
  return new Response(
    `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:48px auto;padding:0 16px;color:#1d1d1f}
button{font-size:17px;padding:12px 20px;border:0;border-radius:8px;color:#fff;cursor:pointer;width:100%}
textarea{width:100%;box-sizing:border-box;font:inherit;padding:8px;margin:8px 0 16px;border-radius:6px;border:1px solid #ccc}
.muted{color:#666;font-size:14px}</style></head><body>${inner}</body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" } },
  );
}

async function dispatch(env, action, date, reason) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "sap-signal-approval-worker",
      "content-type": "application/json",
    },
    body: JSON.stringify({ event_type: ACTIONS[action].event, client_payload: { date, reason: (reason || "").slice(0, 500) } }),
  });
  return r.status === 204 ? null : `GitHub returned ${r.status}: ${(await r.text()).slice(0, 300)}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/decide") return page("Not found", "<p>Not found.</p>", 404);

    if (request.method === "GET") {
      const p = Object.fromEntries(url.searchParams);
      const err = await verify(env, p);
      if (err) return page("Link not valid", `<h2>Link not valid</h2><p>${esc(err)}</p>`, 403);
      const a = ACTIONS[p.action];
      const reasonBox = ["approve", "run", "notes"].includes(p.action) ? "" :
        `<label class="muted">Reason (optional, helps tune the pipeline)</label><textarea name="reason" rows="3"></textarea>`;
      const what = ["run", "notes"].includes(p.action) ? "<p>From your Telegram control panel.</p>" : `<p>Issue <b>${esc(p.date)}</b></p>`;
      return page(a.label, `<h2>${esc(a.label)}</h2>${what}
<form method="post">${["action", "date", "exp", "sig"].map((k) => `<input type="hidden" name="${k}" value="${esc(p[k])}">`).join("")}
${reasonBox}<button style="background:${a.color}">Confirm: ${esc(a.label)}</button></form>
<p class="muted">Nothing happens until you press the button.</p>`);
    }

    if (request.method === "POST") {
      const p = Object.fromEntries(await request.formData());
      const err = await verify(env, p);
      if (err) return page("Link not valid", `<h2>Link not valid</h2><p>${esc(err)}</p>`, 403);
      const failed = await dispatch(env, p.action, p.date, p.reason);
      if (failed) return page("Could not start", `<h2>Could not start the workflow</h2><p>${esc(failed)}</p>`, 502);
      const done = { approve: "Approved. Your LinkedIn kit (article, cover, title, share post) arrives on Telegram in about two minutes.",
        reject: "Issue rejected. Your notes are kept for the next run.",
        regenerate: "This draft is discarded and a fresh one is being generated. Expect a new email in 10 to 20 minutes.",
        run: "A new draft is being built from this week's news and your notes. Expect it by email and Telegram in 10 to 20 minutes.",
        notes: "Your Telegram notes are being collected. The bot confirms in about a minute." };
      return page("Done", `<h2>Done</h2><p>${esc(done[p.action])}</p>`);
    }
    return page("Method not allowed", "<p>Method not allowed.</p>", 405);
  },
};
