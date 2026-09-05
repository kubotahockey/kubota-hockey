# Deploying to the droplet

Notes for getting the live site to match what you see locally.

## First: what is actually running?

Open `https://your-droplet/healthz`. It reports the build string, Flask and
pandas versions, which database file loaded, how many skaters are in it, and
whether JSON output is NaN-safe.

If that 404s, the droplet is running an older `app.py` and nothing below matters
until you fix that.

---

## The five things that cause "it looks different in production"

### 1. Untracked files never left your machine

This is the most likely one. Five templates are **new files**, so `git commit -a`
will not pick them up — `-a` only stages files git already knows about.

```bash
git status --short          # anything with ?? is not going to deploy
git add -A
git commit -m "Redesign, trade analyzer, contract filters"
git push
```

The new files are:

```
templates/trade.html
templates/leaders.html
templates/value.html
templates/compare.html
templates/error.html
DEPLOYING.md
CHANGES.md
```

If `templates/trade.html` is missing on the server, `/trade` throws
`TemplateNotFound` and returns the 500 page. If `static/css/styles.css` did not
get committed, every page renders as unstyled Bootstrap, which looks drastically
different rather than slightly off.

Confirm what the server actually has:

```bash
ssh your-droplet
cd /path/to/app
git log --oneline -1        # same commit you pushed?
ls templates/               # are the new files there?
md5sum static/css/styles.css
```

Compare that checksum against your local one. If they differ, the CSS did not
make it.

### 2. Cached CSS and JS

Handled now, but worth understanding. Every local asset is stamped with the
file's modification time:

```
/static/css/styles.css?v=1788574105
```

The URL changes whenever the file does, so browsers and nginx are forced to
re-fetch. Before this, a visitor who had seen the old site kept the old CSS
indefinitely and saw a broken hybrid.

After deploying, hard-refresh once (Ctrl+Shift+R) to clear anything cached under
the old unversioned URL. If you use Cloudflare in front of the droplet, purge the
cache there too.

### 3. The service was not restarted

Python loads `app.py` once at startup. `git pull` alone changes nothing.

```bash
sudo systemctl restart kubota      # or whatever your unit is called
sudo systemctl status kubota
sudo journalctl -u kubota -n 50    # tracebacks land here
```

If you are running `python app.py` inside `screen` or `tmux`, that is a
development server and it needs killing and restarting by hand. It is also
single-threaded and will feel slow on a droplet — use gunicorn:

```bash
gunicorn -w 2 -b 127.0.0.1:8000 app:app
```

Two workers, not more. Each one loads its own copy of the dataframes.

### 4. nginx is serving `/static` itself

A common nginx config bypasses Flask for static files:

```nginx
location /static/ {
    alias /path/to/flask_app/static/;
    expires 30d;
}
```

If `alias` points at an old checkout, or at a path that no longer exists, the CSS
404s and the site renders unstyled while every HTML page looks fine. Check the
path matches where you actually deployed, then:

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -I https://your-droplet/static/css/styles.css   # expect 200, not 404
```

That `curl` is the fastest way to settle whether this is the problem.

### 5. Linux is case-sensitive, Windows is not

`WHH.PNG` and `whh.png` are the same file on your machine and different files on
the droplet. The screenshots on the home page use uppercase `.PNG`, which matches
what git has recorded, so this should be fine — but if you ever rename an image,
git on Windows may not notice a case-only change. Force it with:

```bash
git mv --force oldname.PNG newname.png
```

---

## The database

`Kubota_Website_PROD.db` is about 27 MB and is committed to the repo. That works,
but two things to watch:

- GitHub warns above 50 MB and refuses above 100 MB. If the file grows, you will
  need Git LFS or an out-of-band copy.
- Every regeneration commits a full new copy, so the repo grows by ~27 MB each
  time. It is already the bulk of your clone size.

Longer term, keeping the database out of git and copying it to the droplet
separately (`scp`, or a small download step on deploy) will keep the repo
manageable. `app.py` supports this already — set `KUBOTA_DB_PATH` to point
anywhere on disk.

---

## Environment

Set the secret key on the server. It falls back to a development value:

```bash
sudo systemctl edit kubota
# [Service]
# Environment="KUBOTA_SECRET_KEY=<something long and random>"
```

Never run the production site with `debug=True`. The `app.run(...)` call at the
bottom of `app.py` is only used when you run the file directly; gunicorn ignores
it.

---

## Quick triage

| What you see | Check first |
|---|---|
| Everything unstyled, plain white | `curl -I .../static/css/styles.css` — 404 means nginx or a missing commit |
| Old design, correct content | Cached CSS; hard-refresh and purge any CDN |
| Some pages 500 | New templates not committed; check `journalctl` |
| Home page images broken | Case mismatch on `.PNG`, or the images did not commit |
| `/healthz` 404s | Old `app.py` — the deploy did not land |
