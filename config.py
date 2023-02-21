#!/usr/bin/python

# Slack webhooks for notifications
posting_webhook = "https://discord.com/api/webhooks/997511728759844915/D_ThpS8KldsJQS0Wwep6RvS-rn_NRLFSuJbqWdZs4gli-sxcLilaAsWQ3tjiBmXHACaS"
errorlogging_webhook = "https://discord.com/api/webhooks/997511728759844915/D_ThpS8KldsJQS0Wwep6RvS-rn_NRLFSuJbqWdZs4gli-sxcLilaAsWQ3tjiBmXHACaS"
# bypass Slack rate limit when using free workplace, switch to False if you're using Pro/Ent version.
discord_sleep_enabled = True
# Add @channel notifications to Slack messages, switch to False if you don't want to use @channel
at_channel_enabled = True

# crtsh postgres credentials, please leave it unchanged.
DB_HOST = 'crt.sh'
DB_NAME = 'certwatch'
DB_USER = 'guest'
DB_PASSWORD = ''
