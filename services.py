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
	return render_template('services-landing.html')

@app.route('/discordauth')
def discordauth():
    scope = request.args.get(
        'scope',
        'identify email')
    discord = make_session(scope=scope.split(' '))
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth2_state'] = state
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    if request.values.get('error'):
        return request.values['error']
    discord = make_session(state=session.get('oauth2_state'))
    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=request.url)
    session['oauth2_token'] = token
    return redirect(url_for('.authme'))

@app.route('/authme')
def authme():

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
    valid_user_query = query_db('select email from pilots where active_account=1 AND in_alliance=1 AND lower(email) = ? limit 1', [email.lower()] )    

    if len(valid_user_query) == 1 and validated:
	#update the pilots record with their discord id
	update_query = insert_db('update pilots set discordid=? where lower(email) = ?', [discordid, email.lower()])

	#check if the pilot is in maincorp
	corp = which_corp(email)
	
	if not corp:
		print "couldn't determine users corp.  Probably an expired key: " + email
		return render_template('services-discord-error.html')


	data = ""

	if corp == WDS_CORP_ID:
		data = AGENT_ROLE_ID
	elif corp == ACADEMY_CORP_ID:
		data = ACADEMY_ROLE_ID
	
	#push a request to the discord api endpoint
	headers = {'user-agent': 'WiNGSPAN External Auth/0.1', 'authorization' : BOT_TOKEN}
	req = requests.patch(API_BASE_URL+'/guilds/'+str(GUILD_ID)+'/members/'+str(discordid), json={'roles':[data]}, headers=headers)
	return render_template('services-discord-success.html')
    else:
	print email + "failed to auth";
	return render_template('services-discord-error.html')

@app.route('/admin')
@app.route('/admin/')
@basic_auth.required
def adminpage():
	#list new accounts to add
	#list accounts to be deleted

	add_to_slack_query = query_db('select name, email from pilots where keyid NOT NULL AND vcode NOT NULL AND slack_active=0 AND active_account=1 AND in_alliance=1')

	add_to_slack=""
	for add in add_to_slack_query:
		add_to_slack = add_to_slack + add['name'] + " <"+ add['email']+">,"

	delete_from_slack = query_db('select name, email from pilots where slack_active=1 AND (active_account=0 OR in_alliance=0)')
	
	return render_template('services-admin.html', add=add_to_slack, delete=delete_from_slack)

@app.route('/admin/accounts-added', methods=['POST'])
@basic_auth.required
def admin_accounts_added():
	update_query = insert_db('update pilots set slack_active=1 where keyid NOT NULL AND vcode NOT NULL AND slack_active=0 AND active_account=1 AND in_alliance=1')
	return redirect(url_for('adminpage'), code=302)

@app.route('/admin/accounts-deleted', methods=['POST'])
@basic_auth.required
def admin_accounts_deleted():
	update_query = insert_db('update pilots set slack_active=0, keyid=NULL, vcode=NULL, active_account=0, in_alliance=0 where slack_active=1 AND (active_account=0 OR in_alliance=0)')
	return redirect(url_for('adminpage'), code=302)

@app.route('/admin/checkaccounts')
@basic_auth.required
def checkaccounts():
	#check for accounts to be disabled
	active_accounts = query_db('select email, keyid, vcode from pilots where active_account=1 AND in_alliance=1 and slack_active=1')

	pilots_to_delete = []

	print "[LOG] Checking %d accounts, this could take some time!" % len(active_accounts)

	for pilot in active_accounts:
		vcode = pilot['vcode']
		keyid = str(pilot['keyid'])
		email = pilot['email']
		if not (pilot_in_alliance(keyid, vcode) and account_active(keyid, vcode)):
			pilots_to_delete.append(email)
			update_query = insert_db('update pilots set active_account=0, in_alliance=0 where lower(email) = ?', [email.lower()])


	print("[LOG] The following accounts are to be removed from Slack: " + ",".join(pilots_to_delete))
	
	#update_query = insert_db('update pilots set active_account=0, in_alliance=0 where lower(email) IN ( ? )', [joined_pilots_to_delete])
	return redirect(url_for('adminpage'), code=302)




@app.route('/new', methods=['POST'])
@app.route('/new/', methods=['POST'])
def new():
	#grap data from the POST
	email = request.form['email']
	name = request.form['name']
	key = request.form['key']
	vcode = request.form['vcode']

	#check that the pilot isn't already in the DB
	if slack_exists(email):
		print("[ERROR] pilot %s already exists" % email)
		return render_template('services-error.html')

	#check that the API is valid
	#check that pilot is in alliance
	#add to db
	if pilot_in_alliance(key,vcode) and account_active(key,vcode):
		insert_db('insert into pilots (email, name, keyid, vcode, active_account, in_alliance, slack_active) values (?, ?, ?, ?, 1, 1, 0)',[email, name, key, vcode])
		print("[INFO] pilot %s new account request success" % email)
		
		discord_invite_token = get_invite_link()

		return render_template('services-success.html', token=discord_invite_token)
	else:
		print("[ERROR] pilot %s not valid" % email)
		return render_template('services-error.html')


@app.route('/update', methods=['POST'])
@app.route('/update/', methods=['POST'])
def update():
	#grap data from the POST
	email = request.form['email']
	key = request.form['key']
	vcode = request.form['vcode']

	#check that the pilot is in our DB
	#check that the API is valid
	#check that pilot is in alliance
	#add to db
	if valid_pilot(email) and pilot_in_alliance(key,vcode) and account_active(key,vcode):
		insert_db('update pilots set keyid=?,vcode=?, active_account=1, in_alliance=1 where lower(email)=?', [key, vcode, email.lower()])
		print("[INFO] pilot %s updated account success" % email)

		#generate an invite link to discord
		discord_invite_token = get_invite_link()

		return render_template('services-success.html', token=discord_invite_token)
	else:
		print("[ERROR] pilot %s not valid" % email)
		return render_template('services-error.html')

def token_updater(token):
    session['oauth2_token'] = token


def make_session(token=None, state=None, scope=None):
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
    results =  query_db('select keyid from pilots where lower(email) = ? limit 1',[email.lower()])

    #fail if a record for this address
    if len(results) >= 1:
	print("[ERROR] %s already exists in pilots table" % email)
	return True

    return False

def valid_pilot(email):
    results =  query_db('select keyid, vcode, id from pilots where lower(email) = ? limit 1',[email.lower()])

    #fail if no record for this address
    if len(results) != 1:
	print("[ERROR] %s not in pilots table" % email)
	return False

    #barf if the api and vcode have already been submitted
    if (results[0][0] or results[0][1]):
	print("[ERROR] %s already has an API or VCODE" % email)
	return False

    return True

def which_corp(email):

    wdsID = WDS_CORP_ID
    waepID = ACADEMY_CORP_ID

    #get the key and vcode from the db
    results =  query_db('select keyid, vcode from pilots where lower(email) = ? limit 1',[email.lower()])

    if len(results) != 1:
	print("[ERROR] %s not in pilots table" % email)
	return False   

    key = results[0][0]
    vcode = results [0][1]
    url = "https://api.eveonline.com/account/Characters.xml.aspx?keyId="+str(key)+"&vCode="+vcode

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
			print("[INFO] pilot %s is in WDS" % pilotName)

		if corpID == waepID and not corp:
			corp = corpID
			print("[INFO] pilot %s is in WAEP" % pilotName)
    except Exception,e:
		print "[WARN] barfed in XML api", sys.exc_info()[0]
		print str(e)

    return corp



def pilot_in_alliance(key, vcode):

    url = "https://api.eveonline.com/account/Characters.xml.aspx?keyId="+key+"&vCode="+vcode
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
			print("[INFO] pilot %s is in alliance" % pilotName)

    except Exception,e:
		print "[WARN] barfed in XML api", sys.exc_info()[0]
		print str(e)

    return response

def account_active(key, vcode):

    url = "https://api.eveonline.com/account/AccountStatus.xml.aspx?keyId="+key+"&vCode="+vcode

    response = False	
    try:
	root = ET.fromstring(requests.get(url).content)

	# sample time
	# 2016-03-29 19:39:26
	currentTime = datetime.strptime(root.find('currentTime').text, "%Y-%m-%d %H:%M:%S") 
	paidUntil = datetime.fromtimestamp(1)

	for child in root:
   	   if child.tag == "result":
		print child.find('paidUntil').text
		paidUntil = datetime.strptime(child.find('paidUntil').text, "%Y-%m-%d %H:%M:%S")		
	
	if paidUntil > currentTime:
		response = True
		print("[INFO] account active %s %s" % (key, vcode))
	else:
		print paidUntil
		print currentTime
	
    except Exception,e:
		print "[WARN] barfed in XML api", sys.exc_info()[0]
		print str(e)
	
    return response

def get_invite_link():
	
	max_age = 86400
	max_uses = 5
#	xkcdpass = True
	headers = {'user-agent': 'WiNGSPAN External Auth/0.1', 'authorization' : BOT_TOKEN}
	channelid = "172888490608951297"
	
	req = requests.post(API_BASE_URL+'/channels/'+channelid+'/invites', json={'max_age':max_age, 'max_uses':max_uses}, headers=headers)
	return req.json()['code']


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_db()

    db.row_factory = sqlite3.Row

    return db

def connect_db():
    return sqlite3.connect(database)

def insert_db(query, args=()):
    # g.db is the database connection
    cur = get_db().execute(query, args)
    get_db().commit()
    cur.close()


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
