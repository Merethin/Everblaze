# Self-hosting the Discord bot

The discord bot can be found in `bot.py`. To self-host it yourself, go to https://discord.com/developers/applications, create a new application, go to the "Bot" section and copy its token.

Create a file called `.env` and paste the token like this:
```
TOKEN = "<TOKEN>"
```

Still on the "Bot" tab, enable "Message Content Intent" and "Server Members Intent".

To invite the bot to a server, go to the "Installation" tab, copy the discord provided Install Link, and go to the Oauth2 tab.

Paste the install link into "Redirects" and configure the permissions in the following way.

"OAuth2 URL Generator":
Check "messages.read", "bot", "guilds.members.read" and "applications.commands".
Select the previously pasted install link in "Select Redirect URL."

"Bot Permissions":
Check "Send Messages", "Embed Links", "Mention Everyone", and "Use Slash Commands".

After this, you can copy the "generated URL" given to you by Discord. This is the install link for your bot. Paste it in your browser, select a server, and you're done. Now run the bot.

```
python bot.py -n <NATION_NAME> -r -e 3600
```

The `-e` flag will exit the bot a given number of seconds after the end of update. It is recommended to combine this with a service manager to restart the bot again with the `-r` flag set, ensuring the database is refreshed after every update.