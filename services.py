from flask import Flask, request, render_template, g, redirect, url_for, session, jsonify
from flask.ext.basicauth import BasicAuth
from datetime import datetime
import sqlite3
import string
import sys
import requests
import yaml
import xml.etree.ElementTree as ET
import requests
import os
import json
from requests_oauthlib import OAuth2Session

app = Flask(__name__)

database = 'agentapi.db'

config = yaml.load(file('services.conf', 'r'))

GUILD_ID = config['GUILD_ID']

OAUTH2_CLIENT_ID = config['OAUTH2_CLIENT_ID']
OAUTH2_CLIENT_SECRET = config['OAUTH2_CLIENT_SECRET']
OAUTH2_REDIRECT_URI = config['OAUTH2_REDIRECT_URI']
BOT_TOKEN = config['BOT_TOKEN']

API_BASE_URL = 'https://discordapp.com/api'
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

if 'http://' in OAUTH2_REDIRECT_URI:
  os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'

app.config['BASIC_AUTH_USERNAME'] = config['BASIC_AUTH_USERNAME']
app.config['BASIC_AUTH_PASSWORD'] = config['BASIC_AUTH_PASSWORD']
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

WDS_CORP_ID = "98330748"
ACADEMY_CORP_ID = "98415327"

basic_auth = BasicAuth(app)


@app.route('/')
def default():
  """
  Default landing page for services.
  """
  return render_template('services-landing.html')

@app.route('/discordauth')
def discordauth():
  """
  Method creates authorized discord session, 
  sets auth state and redirects to authed url.
  """
  scope = request.args.get(
      'scope',
      'identify email')
  discord = make_session(scope=scope.split(' '))
  authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
  session['oauth2_state'] = state
  return redirect(authorization_url)

@app.route('/callback')
def callback():
  """
  Method sets OAuth2 session token, otherwise returns an error.
  """
  if request.values.get('error'):
    return request.values['error']
  discord = make_session(state=session.get('oauth2_state'))
  token = discord.fetch_token(
    TOKEN_URL,
    client_secret = OAUTH2_CLIENT_SECRET,
    authorization_response=request.url)
  session['oauth2_token'] = token
  return redirect(url_for('.authme'))

@app.route('/authme')
def authme():
  """
  Method validates pilot email, if account is active/incorp and updates
  DB with discord ID and pushes new member to discord API.
  """
  ACADEMY_ROLE_ID = '172888937453322240'
  AGENT_ROLE_ID = '172888812991676416'

  discord = make_session(token=session.get('oauth2_token'))
  user = discord.get(API_BASE_URL + '/users/@me').json()
 
  email = user['email']
  validated = user['verified']
  discordid = user['id']
 
  #app 500s if email doesn't exist
  if not email or not validated or not discordid:
    print "failed due to blank email, validated or discordid"
    return render_template('services-discord-error.html')
  #print email + " " + validated
  
  #check that the email address is valid, the account is active and in corp
  valid_user_query = query_db('SELECT email FROM pilots '
                              'WHERE active_account=1 '
                              'AND in_alliance=1 ' 
                              'AND lower(email) = ? '
                              'LIMIT 1', [email.lower()])
  
  if len(valid_user_query) == 1 and validated:
    #update the pilots record with their discord id
    update_query = insert_db('UPDATE pilots '
                             'SET discordid=? '
                             'WHERE lower(email) = ?', [discordid, email.lower()])
    #check if the pilot is in maincorp
    corp = which_corp(email)

    if not corp:
      print "couldn't determine users corp.  Probably an expired key: {email}".format(email=email)
      return render_template('services-discord-error.html')

    data = ""

    if corp == WDS_CORP_ID:
      data = AGENT_ROLE_ID
    elif corp == ACADEMY_CORP_ID:
      data = ACADEMY_ROLE_ID
	 
    #push a request to the discord api endpoint
    headers = {'user-agent': 'WiNGSPAN External Auth/0.1', 'authorization' : BOT_TOKEN}
    uri = '{base}/guilds/{guildid}/members/{discordid}'.format(base = API_BASE_URL,
                                                               guildid = GUILD_ID,
                                                               discordid = discordid)
    req = requests.patch(uri, json = {'roles':[data]}, headers = headers)

    return render_template('services-discord-success.html')

  else:
    print '{email} failed to auth'.format(email = email)
    return render_template('services-discord-error.html')

@app.route('/admin')
@app.route('/admin/')
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

  delete_from_slack = query_db('SELECT name, email, keyid, vcode '
                               'FROM pilots '
                               'where slack_active=1 '
                               'AND (active_account=0 '
                               'OR in_alliance=0)')
	
  return render_template('services-admin.html', add=add_to_slack, delete=delete_from_slack)

@app.route('/admin/accounts-added', methods=['POST'])
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

  return redirect(url_for('adminpage'), code=302)

@app.route('/admin/accounts-deleted', methods=['POST'])
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
    email = user['email']

    #push requests to the discord api endpoint, to remove roles and message the user to explain the action
    headers = {'user-agent': 'WiNGSPAN External Auth/0.1', 'authorization' : BOT_TOKEN}
    uri = '{base}/guilds/{guildid}/members/{discordid}'.format(base = API_BASE_URL,
                                                               guildid = GUILD_ID,
                                                               discordid = discordid)

    print "[LOG] Removing discord roles for {email}".format(email=email)
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

  return redirect(url_for('adminpage'), code=302)

@app.route('/admin/checkaccounts')
@basic_auth.required
def checkaccounts():
  """
  Method checks DB for expired accounts, then deletes them.
  """
  active_accounts = query_db('SELECT email, keyid, vcode from pilots '
                             'WHERE active_account=1 '
                             'AND in_alliance=1 '
                             'AND slack_active=1')
  pilots_to_delete = []

  print "[LOG] Checking {n} accounts, this could take some time!".format(n = len(active_accounts))

  for pilot in active_accounts:
		vcode = pilot['vcode']
		keyid = str(pilot['keyid'])
		email = pilot['email']
		if not (pilot_in_alliance(keyid, vcode) and account_active(keyid, vcode)):
			pilots_to_delete.append(email)
			update_query = insert_db('UPDATE pilots '
                               'SET active_account=0, in_alliance=0 '
                               'WHERE lower(email) = ?', [email.lower()])

  print("[LOG] The following accounts are to be removed from Slack: " + ",".join(pilots_to_delete))
	
  # Expected String: update_query = insert_db('update pilots set active_account=0, in_alliance=0 where lower(email) IN ( ? )', [joined_pilots_to_delete])
  return redirect(url_for('adminpage'), code=302)


@app.route('/new', methods=['POST'])
@app.route('/new/', methods=['POST'])
def new():
  """
  Method grabs new pilot data from form, checks to ensure
  the API is valid, pilot is in alliance, and not already in DB, then adds it.
  """
  email = request.form['email']
  name = request.form['name']
  key = request.form['key']
  vcode = request.form['vcode']

  if slack_exists(email):
    print("[ERROR] pilot {email} already exists".format(email = email))
    return render_template('services-error.html')

  if pilot_in_alliance(key, vcode) and account_active(key, vcode):
    insert_db('INSERT INTO pilots (email, name, keyid, vcode, active_account, in_alliance, slack_active) '
              'VALUES (?, ?, ?, ?, 1, 1, 0)', [email, name, key, vcode])
    print("[INFO] pilot {email} new account request success".format(email = email))
		
    discord_invite_token = get_invite_link()

    return render_template('services-success.html', token=discord_invite_token)
  else:
    print("[ERROR] pilot {email} not valid".format(email = email))
    return render_template('services-error.html')


@app.route('/update', methods = ['POST'])
@app.route('/update/', methods = ['POST'])
def update():
  """
  Method gets updated information for form, checks to ensure
  API is valid, pilot is in the DB/alliance then updates records.
  """
  email = request.form['email']
  key = request.form['key']
  vcode = request.form['vcode']

  if valid_pilot(email) and pilot_in_alliance(key, vcode) and account_active(key, vcode):
    insert_db('UPDATE pilots '
              'SET keyid=?,vcode=?, active_account=1, in_alliance=1 '
              'WHERE lower(email) = ?', [key, vcode, email.lower()])
    print("[INFO] pilot {email} updated account success".format(email = email))

    #generate an invite link to discord
    discord_invite_token = get_invite_link()

    return render_template('services-success.html', token=discord_invite_token)
  else:
    print("[ERROR] pilot {email} not valid".format(email = email))
    return render_template('services-error.html')

def token_updater(token):
  """
  Method updates OAuth2 token.
  """
  session['oauth2_token'] = token


def make_session(token=None, state=None, scope=None):
  """
  Method creates OAuth2 session providing the token, state, and scope.
  Returns OAuth 2 Session Object
  """
  return OAuth2Session(
      client_id=OAUTH2_CLIENT_ID,
      token=token,
      state=state,
      scope=scope,
      redirect_uri=OAUTH2_REDIRECT_URI,
      auto_refresh_kwargs={

        'client_id': OAUTH2_CLIENT_ID,
        'client_secret': OAUTH2_CLIENT_SECRET,
      },
      auto_refresh_url=TOKEN_URL,
      token_updater=token_updater)

def slack_exists(email):
  """
  Method verifies slack user exists in database. Returns True/False.
  """
  results =  query_db('SELECT keyid '
                      'FROM pilots '
                      'WHERE lower(email) = ? '
                      'LIMIT 1', [email.lower()])

  #fail if a record for this address
  if len(results) >= 1:
    print("[ERROR] {email} already exists in pilots table".format(email = email))
    return True

  return False

def valid_pilot(email):
  """
  Method returns false if pilot doesn't exits in table, or has API or Vcode.
  Returns True/False.
  """
  results =  query_db('SELECT keyid, vcode, id '
                      'FROM pilots '
                      'WHERE lower(email) = ? limit 1', [email.lower()])

  #fail if no record for this address
  if len(results) != 1:
	  print("[ERROR] {email} not in pilots table".format(email = email))
	  return False

    #barf if the api and vcode have already been submitted
  if (results[0][0] or results[0][1]):
    print("[ERROR] {email} already has an API or VCODE".format(email = email))
    return False

  return True

def which_corp(email):
  """
  Method checks if pilots is in corp. Returns corpID Integer.
  """
  wdsID = WDS_CORP_ID
  waepID = ACADEMY_CORP_ID

  #get the key and vcode from the db
  results =  query_db('SELECT keyid, vcode '
                      'FROM pilots '
                      'WHERE lower(email) = ? '
                      'LIMIT 1',[email.lower()])

  if len(results) != 1:
	  print("[ERROR] {email} not in pilots table".format(email = email))
	  return False   

  key = results[0][0]
  vcode = results [0][1]
  url = ('https://api.eveonline.com/account/Characters.xml.aspx?'
         'keyId={key}&vCode={vcode}'.format(key = str(key), vcode = vcode))

  corp =""

  try:
    root = ET.fromstring(requests.get(url).content)
	
    #grab all of the pilots returned
    pilots = list(root.iter('row'))
		
    for pilot in pilots:
      corpID =  pilot.get('corporationID')
      pilotName = pilot.get('name')

      if corpID == wdsID:
        corp = corpID
        print("[INFO] pilot {name} is in WDS".format(name = pilotName))

      if corpID == waepID and not corp:
        corp = corpID
        print("[INFO] pilot {name} is in WAEP".format(name = pilotName))

  except Exception,e:
    print "[WARN] barfed in XML api", sys.exc_info()[0]
    print str(e)

  return corp



def pilot_in_alliance(key, vcode):
  """
  Method checks if pilot is in the alliance. Returns True/False
  """
  url = ('https://api.eveonline.com/account/Characters.xml.aspx?'
         'keyId={key}&vCode={vcode}'.format(key = key, vcode = vcode))
  #wdsAllianceID = "99005770"

  wdsID = WDS_CORP_ID
  waepID = ACADEMY_CORP_ID

  response = False	
  try:
    root = ET.fromstring(requests.get(url).content)

    #grab all of the pilots returned
    pilots = list(root.iter('row'))
		
    for pilot in pilots:
      corpID =  pilot.get('corporationID')
      pilotName = pilot.get('name')

      if corpID == wdsID or corpID == waepID:
        response = True
        print("[INFO] pilot {name} is in alliance".format(name = pilotName))

  except Exception,e:
    print "[WARN] barfed in XML api", sys.exc_info()[0]
    print str(e)

  return response

def account_active(key, vcode):
  """
  Method checks if pilot account is active. Returns True/False.
  """
  url = ('https://api.eveonline.com/account/AccountStatus.xml.aspx?'
         'keyId={key}&vCode={vcode}'.format(key = key, vcode = vcode))

  response = False	
  try:
    root = ET.fromstring(requests.get(url).content)

    # sample time
    # 2016-03-29 19:39:26
    currentTime = datetime.strptime(root.find('currentTime').text, "%Y-%m-%d %H:%M:%S") 
    paidUntil = datetime.fromtimestamp(1)

    for child in root:
      if child.tag == "result":
        #print child.find('paidUntil').text
        paidUntil = datetime.strptime(child.find('paidUntil').text, "%Y-%m-%d %H:%M:%S")		
	
        if paidUntil > currentTime:
          response = True
          print("[INFO] account active {key} {vcode}".format(key = key, vcode = vcode))
        else:
          print("[INFO] account inactive {key} {vcode}".format(key = key, vcode = vcode))
  
  except Exception,e:
    print "[WARN] barfed in XML api", sys.exc_info()[0]
    print str(e)
	
  return response

def get_invite_link():
  """
  Method requests an invite link to specified channel (General). Returns url string.
  """
  max_age = 86400
  max_uses = 5
#	xkcdpass = True
  headers = {'user-agent': 'WiNGSPAN External Auth/0.1', 'authorization' : BOT_TOKEN}
  # General Channel
  channelid = "172888490608951297"
	
  uri = ('{base}/channels/{cid}/invites'.format(base = API_BASE_URL, cid = channelid))
  req = requests.post(uri, json={'max_age':max_age, 'max_uses':max_uses}, headers=headers)

  return req.json()['code']


def query_db(query, args=(), one=False):
  """
  Method returns SQL elements from DB.
  """
  cur = get_db().execute(query, args)
  rv = cur.fetchall()
  cur.close()
  return (rv[0] if rv else None) if one else rv


def get_db():
  """
  Method checks if DB exists, if not creates connection. 
  Returns DB connection object.
  """
  db = getattr(g, '_database', None)
  if db is None:
    db = g._database = connect_db()

  db.row_factory = sqlite3.Row

  return db

def connect_db():
  """
  Connects to DB.
  """
  return sqlite3.connect(database)

def insert_db(query, args=()):
  """
  Method inserts elements into DB, then closes the connection.
  """
  # g.db is the database connection
  cur = get_db().execute(query, args)
  get_db().commit()
  cur.close()

@app.teardown_appcontext
def close_connection(exception):
  """
  Method ensures on __exit__ connection objects are garbage collected.
  """
  db = getattr(g, '_database', None)
  if db is not None:
    db.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
