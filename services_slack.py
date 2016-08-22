
from slackclient import SlackClient
import json

def init(token):
  global api_client
  api_client = SlackClient(token)

def invite_to_slack(email, name):
  api_client.api_call('users.admin.invite', email=email, set_active=True, first_name=name)

  return

#paid tier only
def deactivate_slack(email):
  userid=get_userid(email)
  print(userid)
  api_client.api_call('users.admin.setInactive', user=userid, set_active=True)

  return

#paid tier only
def activate_slack(email):
  userid=get_userid(email)
  print(userid)
  api_client.api_call('users.admin.setRegular', user=userid, set_active=True)

  return

def get_userid(email):
  users = api_client.api_call('users.list')['members']

  return [x.get('id') for x in users if x['profile'].get('email') == email]


  
