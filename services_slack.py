
from slackclient import SlackClient
import json

def invite_to_slack(token, email, name):
  client = SlackClient(token)

  client.api_call('users.admin.invite', email=email, set_active=True, first_name=name)

  return
