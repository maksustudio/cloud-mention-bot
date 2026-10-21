# Cloud Interactive mention bot

When someone mentions a dev in the server, the bot sends that dev a DM with who mentioned them, the channel, a preview of the message and a link to it.

- It only DMs people who can see that channel, so private channels stay private.
- It skips @everyone and @here, other bots, and the person who wrote the message.
- It sends at most one DM per person every 5 minutes. Pings that come in during that window are grouped and sent together in one DM, so nothing is lost.
- The first time it DMs someone, it explains what it is first, so nobody gets confused.
- Role mentions (like @modelers) are off by default. Turn them on with `ROLE_MENTIONS=true`.

## 1. Create the bot (Discord Developer Portal)

1. Go to https://discord.com/developers/applications and click **New Application**. Name it, for example "Cloud Pings".
2. Open the **Bot** tab:
   - Click **Reset Token** and copy the token. It's only shown once. Don't paste it in any Discord chat.
   - Under **Privileged Gateway Intents**, turn on **Message Content Intent**. Also turn on **Server Members Intent** if you'll use role mentions.
3. Open **OAuth2**, copy the **Client ID**, and open this link with that ID in it:
   `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot&permissions=1024`
   (1024 = View Channels only, which is all the bot needs.) Pick the Cloud Interactive server.

## 2. Host it (always on)

Easiest option: **Railway**.

1. Upload this folder to a private GitHub repo. `.env` is already in `.gitignore`, so the token never goes up.
2. On railway.app: New Project, then Deploy from GitHub repo, then pick the repo.
3. Under **Variables**, add the ones in `.env.example`. At minimum: `DISCORD_TOKEN` and `GUILD_ID`.
4. Railway reads the `Procfile` and runs `python bot.py`. When the logs show "Logged in as ...", it's working.

Any cheap VPS also works: `pip install -r requirements.txt`, then `python bot.py`, with the variables in the environment.

## 3. Test it

Have someone mention you in a channel. A DM from the bot should arrive in a few seconds.

## Settings

| Variable | What it does |
|---|---|
| `DISCORD_TOKEN` | Bot token (required) |
| `GUILD_ID` | Server id, so the bot only works there |
| `ROLE_MENTIONS` | `true` also DMs everyone in a mentioned role |
| `COOLDOWN_SECONDS` | Minimum seconds between DMs to the same person (default 300 = 5 min) |
| `IGNORE_CHANNEL_IDS` | Comma-separated channels where pings are not forwarded |
| `IGNORE_USER_IDS` | Comma-separated people who don't want DMs |
