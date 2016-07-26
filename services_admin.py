from flask import render_template, Blueprint, url_for, redirect, request
from flask.ext.basicauth import BasicAuth
from multiprocessing import Pool
import requests
import pprint

from services_util import *

services_admin = Blueprint('services_admin', __name__)

basic_auth = BasicAuth()

#hack
@services_admin.record_once
def on_load(state):
  basic_auth.init_app(state.app)

@services_admin.route('/')
@basic_auth.required
def adminpage():
  """
  Method returns accounts with pending New/Delete status.
  """
  add_to_slack_query = query_db('SELECT name, email from pilots '
                                'WHERE keyid NOT NULL '
                                'AND vcode NOT NULL ' 
                                'AND slack_active=0 '
                                'AND active_account=1 '
                                'AND in_alliance=1')
  add_to_slack=""
  for add in add_to_slack_query:
    add_to_slack = add_to_slack + add['name'] + " <"+ add['email']+">,"

  delete_from_slack = query_db('SELECT name, email, keyid, vcode, id '
                               'FROM pilots '
                               'where slack_active=1 '
                               'AND (active_account=0 '
                               'OR in_alliance=0)')
	
  return render_template('services-admin.html', add=add_to_slack, delete=delete_from_slack)

@services_admin.route('/accounts-added', methods=['POST'])
@basic_auth.required
def admin_accounts_added():
  """
  Method updates DB with new pilots.
  """
  update_query = insert_db('UPDATE pilots '
                           'SET slack_active=1 '
                           'WHERE keyid NOT NULL '
                           'AND vcode NOT NULL '
                           'AND slack_active=0 '
                           'AND active_account=1 '
                           'AND in_alliance=1')

  return redirect(url_for('services_admin.adminpage'), code=302)

@services_admin.route('/accounts-deleted', methods=['POST'])
@basic_auth.required
def admin_accounts_deleted():
  """
  Method updates DB with deleted pilots.
  """
  users_to_delete = query_db('SELECT email, discordid '
                             'FROM pilots '
                             'WHERE slack_active=1 ' 
                             'AND (active_account=0 '
                             'OR in_alliance=0)')

  update_query = insert_db('UPDATE pilots '
                           'SET slack_active=0, keyid=NULL, vcode=NULL, active_account=0, in_alliance=0 '
                           'WHERE slack_active=1 '
                           'AND (active_account=0 '
                           'OR in_alliance=0)')

  #remove discord roles
  for user in users_to_delete:
    discordid = user['discordid']

    #skip if we don't have a discordid
    if not discordid:
      continue

    email = user['email']

    #push requests to the discord api endpoint, to remove roles and message the user to explain the action
    headers = {'user-agent': 'WiNGSPAN External Auth/0.1', 'authorization' : BOT_TOKEN}
    uri = '{base}/guilds/{guildid}/members/{discordid}'.format(base = API_BASE_URL,
                                                               guildid = GUILD_ID,
                                                               discordid = discordid)

    print("[LOG] Removing discord roles for {email}".format(email=email))
    req = requests.patch(uri, json = {'roles':''}, headers = headers)

    #create a DM channel with the user
    uri ='{base}/users/@me/channels'.format(base = API_BASE_URL)
    req = requests.post(uri, json = {'recipient_id':discordid}, headers=headers)

    dmid = req.json()['id']

    message = """Your Discord roles have been revoked, either because you left the alliance, your account expired or your API key has expired. \r\n
              If you believe this is an error, please submit a valid API key for this email address to https://services.torpedodelivery.com and then type !authme
              Otherwise, please feel free to hangout in our public channels.\r\n
              Cheers! ~authbot"""

    uri ='{base}/channels/{dmid}/messages'.format(base = API_BASE_URL,
                                                  dmid = dmid)
    req = requests.post(uri, json = {'content':message}, headers=headers)

  return redirect(url_for('services_admin.adminpage'), code=302)

@services_admin.route('/checkaccounts')
@basic_auth.required
def checkaccounts():
  """
  Method checks DB for expired accounts, updates DB with the prep-for-delete flag.
  """
  active_accounts = query_db('SELECT email, keyid, vcode from pilots '
                             'WHERE active_account=1 '
                             'AND in_alliance=1 '
                             'AND slack_active=1')

  print("[LOG] Checking {n} accounts.".format(n = len(active_accounts)))

  #turn our dictionary into a list
  accountlist = []
  for account in active_accounts:
    accountlist.append([account['email'], str(account['keyid']), account['vcode']])

  pool = Pool(10)
  pilots_to_delete = pool.starmap(in_alliance_and_active, accountlist)

  pool.close()
  pool.join()

  filtered_delete = list(filter(None.__ne__, pilots_to_delete))

  pp = pprint.PrettyPrinter(indent=4)
  pp.pprint(filtered_delete)

  for email in filtered_delete:
    update_query = insert_db('UPDATE pilots '
                             'SET active_account=0, in_alliance=0 '
                             'WHERE lower(email) = ?', [email.lower()])

  return redirect(url_for('services_admin.adminpage'), code=302)

@services_admin.route('/markactive', methods=['POST'])
@basic_auth.required
def admin_mark_active():
  """
  Method marks a provided pilot as in corp and active
  """
  pilotid = request.form['id']
  insert_db('UPDATE pilots SET active_account=1, in_alliance=1 WHERE id=?', [pilotid])
  print("[INFO] pilot {pilotid} marked as active".format(pilotid = pilotid))

  return redirect(url_for('services_admin.adminpage'), code=302)

