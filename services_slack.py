
from slackclient import SlackClient
import json

def invite_to_slack(token, email):
  client = SlackClient(token)

  client.api_call('users.admin.invite', email=email, set_active=True)

  return
