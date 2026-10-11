# Setting yt-kids up: the token and the secrets

Everything below is done once. Nothing here can be done by the code, because each step needs
the owner of the kids channel to be signed in and to click Allow.

## 1. The YouTube channel

The channel has to exist and be set as **made for kids** at channel level:

YouTube Studio > Settings > Channel > Advanced settings > **Audience: Yes, set this channel as
made for kids.**

That is the channel half of the COPPA requirement. The other half - every video declared made
for kids - is in `pipeline/upload.py` and cannot be switched off by editing config.

Consequences, none of which the code depends on: comments are off, end screens and cards do not
work, subscribers are not notified of new uploads, personalised ads are off.

## 2. The token (`youtube.upload`, one permission, nothing else)

Use the **same Google Cloud project and the same `credentials.json`** as yt-factory, signed in
as the account that owns the *kids* channel. A second project would need its own API audit; the
audit already in progress is for the first one, and a project can authorise more than one
channel.

1. Copy `credentials.json` from `C:\yt-factory\` into `C:\yt-kids\` (it is in `.gitignore`).
2. `cd C:\yt-kids` then `python scripts\youtube_auth.py`
3. A browser opens. **Choose the account that owns the kids channel**, not the Stoicism one.
   If Google says the app is not verified: *Advanced > Go to the app*. Press **Allow** on the
   single permission it asks for, "upload videos".
4. It saves `secrets\token.json`.

## 3. The repository

Create a **public** repository, for example `yt-kids-daily`, and push `C:\yt-kids` to it. Public
means anything ever committed is public forever: `.env`, `secrets/`, `output/` and
`credentials.json` are already in `.gitignore`.

Commits should go out under the GitHub noreply address of the account used, not a personal
e-mail:

    git config user.email "<id>+<username>@users.noreply.github.com"

## 4. The secrets (Settings > Secrets and variables > Actions > New repository secret)

| name | what | where from |
|---|---|---|
| `YOUTUBE_TOKEN_JSON` | the whole contents of `secrets\token.json` | step 2 |
| `CLOUDFLARE_ACCOUNT_ID` | this project's own account id | Cloudflare dashboard |
| `CLOUDFLARE_API_TOKEN` | this project's own token, Workers AI read | Cloudflare dashboard |
| `PIXABAY_API_KEY` | only the grow job uses it, to find new clips | pixabay.com/api/docs |

`credentials.json` is deliberately **not** a secret in the repository: its client id and secret
are already inside `token.json`.

## 5. Switch it on

Actions > daily > **Run workflow** once by hand. It publishes to the YouTube queue three days
ahead at 16:00 Kyiv time; the schedule then runs it every day, with a second attempt later the
same day, and the heartbeat and publish-check workflows watch it.
