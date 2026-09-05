# Deploying Walkout

The image runs the console and the agent. It needs a ClickHouse cluster that
already has data in it and a Gemini API key; it does not need a build step, a
database add-on, or a start command, because `railway.json` and the `Dockerfile`
carry all of that.

## Before you start

Have the cluster loaded. From your laptop, once:

```bash
make load        # safe to repeat -- creates anything missing, deletes nothing
make simulate    # ~4 minutes, 13.1M events
make doctor      # should print the row count
```

The deployed app reads the same cluster, so this is done once, not per deploy.

## Railway

1. **New Project → Deploy from GitHub repo → `martinvibes/walkout`.**
   Railway reads `railway.json`, sees `"builder": "DOCKERFILE"`, and builds the
   `Dockerfile`. Do not set a build or start command; the image has both.

2. **Variables → RAW Editor**, and paste these keys with the values from your
   local `.env`:

   ```
   CLICKHOUSE_HOST=...
   CLICKHOUSE_PORT=8443
   CLICKHOUSE_USER=default
   CLICKHOUSE_PASSWORD=...
   CLICKHOUSE_SECURE=true
   CLICKHOUSE_DATABASE=walkout
   GOOGLE_GENAI_USE_VERTEXAI=false
   GOOGLE_API_KEY=...
   ```

   `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` are for Vertex mode and
   are not needed here. Do not set `PORT` or `HOST` either: Railway injects
   `PORT`, and the image already binds `0.0.0.0`.

3. **Settings → Networking → Generate Domain.** Railway gives you
   `something.up.railway.app`. That is the hosted URL the submission needs.

4. **Watch the deploy log.** The health check hits `/api/health`, which runs a
   real `count()` against ClickHouse rather than just proving the process
   started, so a green check means the whole path works. It goes healthy in
   about fifteen seconds.

5. **Verify:**

   ```bash
   curl https://YOUR-DOMAIN/api/health
   # {"ok":true,"events":13065665}
   ```

   Then open the domain. The console should draw the retention curve, mark
   three cliffs, and show the last agent investigation under "The agent".

## If the health check fails

The log says which of the two dependencies is unhappy.

- `CLICKHOUSE_PASSWORD is not set` — a variable did not save. Re-paste in the
  RAW editor and redeploy.
- A connection timeout — ClickHouse Cloud idles a service that has not been
  queried for a while and takes ~30s to wake. The restart policy retries three
  times, which is normally enough; if not, open the cluster in the ClickHouse
  console once to wake it and redeploy.
- `events: 0` with `ok: true` — the cluster is reachable but empty. Run
  `make simulate` from your laptop against the same credentials.

## Quota

A full investigation costs about seven model calls, and a free-tier key allows
20 per day per model. The page therefore replays the last stored investigation
from `walkout.agent_reports` instead of running a new one on every visit, and
only spends calls when someone presses the button.

If the button starts returning quota errors, either wait for the daily reset or
point `WALKOUT_MODEL` at another model — each has its own daily pool. Setting
`WALKOUT_MODEL=gemini-3.7-flash` in Railway variables is a one-line fix that
takes effect on the next deploy.
