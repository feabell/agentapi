from flask import Flask
from flask import request
from flask import render_template
from flask import g
from flask import redirect
from flask import url_for
from flask.ext.basicauth import BasicAuth
from datetime import datetime
import sqlite3
import string
import sys
import requests
import yaml
import xml.etree.ElementTree as ET

app = Flask(__name__)

database = 'agentapi.db'

config = yaml.load(file('services.conf', 'r'))

app.config['BASIC_AUTH_USERNAME'] = config['BASIC_AUTH_USERNAME']
app.config['BASIC_AUTH_PASSWORD'] = config['BASIC_AUTH_PASSWORD']

basic_auth = BasicAuth(app)

@app.route('/')
def default():
	return render_template('services-landing.html')


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



@app.route('/new', methods=['POST'])
@app.route('/new/', methods=['POST'])
def new():
	#grap data from the POST
	email = request.form['email']
	name = request.form['name']
	key = request.form['key']
	vcode = request.form['vcode']

	#check that the pilot isn't already in the DB
	if valid_pilot(email):
		print("pilot %s already exists" % email)
		return render_template('services-error.html')

	#check that the API is valid
	#check that pilot is in alliance
	#add to db
	if pilot_in_alliance(key,vcode) and account_active(key,vcode):
		insert_db('insert into pilots (email, name, keyid, vcode, active_account, in_alliance, slack_active) values (?, ?, ?, ?, 1, 1, 0)',[email, name, key, vcode])
		return render_template('services-success.html')
	else:
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
		insert_db('update pilots set keyid=?,vcode=?, active_account=1, in_alliance=1 where email=?', [key, vcode, email])
		return render_template('services-success.html')
	else:
		return render_template('services-error.html')

def valid_pilot(email):
    results =  query_db('select keyid, vcode, id from pilots where lower(email) = ? limit 1',[email.lower()])

    #fail if no record for this address
    if len(results) != 1:
	print("Not a valid pilot")
	return False

    #barf if the api and vcode have already been submitted
    if (results[0][0] or results[0][1]):
	return False

    return True

def pilot_in_alliance(key, vcode):

    url = "https://api.eveonline.com/account/Characters.xml.aspx?keyId="+key+"&vCode="+vcode
    #wdsAllianceID = "99005770"
    wdsID = "98330748"
    waepID = "98415327"

    response = False	
    try:
	root = ET.fromstring(requests.get(url).content)
	
	#grab all of the pilots returned
	pilots = list(root.iter('row'))
		
	for pilot in pilots:
		corpID =  pilot.get('corporationID')

		if corpID == wdsID or corpID == waepID:
			response = True
			print "pilot in alliance"

    except Exception,e:
		print "barfed in XML api", sys.exc_info()[0]
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

	for child in root:
   	   if child.tag == "result":
		paidUntil = datetime.strptime(child.find('paidUntil').text, "%Y-%m-%d %H:%M:%S")		
	
	if paidUntil > currentTime:
		response = True
		print "account active"
	
    except Exception,e:
		print "barfed in XML api", sys.exc_info()[0]
		print str(e)
	
    return response

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
