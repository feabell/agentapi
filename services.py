from flask import Flask
from flask import request
from flask import render_template
from flask import g
from datetime import datetime, timedelta
import sqlite3
import string
import random
import json

app = Flask(__name__)

database = 'agentapi.db'

@app.route('/')
def default():
	return render_template('services-landing.html')


@app.route('/admin')
def adminpage():
	#do some auth bullshit
	#list new accounts to add
	#list accounts to be deleted
	return	

@app.route('/new', methods=['POST'])
@app.route('/new/', methods=['POST'])
def new():
	#grap data from the POST
	email = request.form['email']
	name = request.form['name']
	key = request.form['key']
	vcode = request.form['vcode']

	api=1	
	#check that the API is valid
	#check that pilot is in alliance
	#add to db
	if valid_api(api) and pilot_in_alliance(api) and account_active(api):
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

	api=1
	#check that the pilot is in our DB
	#check that the API is valid
	#check that pilot is in alliance
	#add to db
	if valid_pilot(email) and valid_api(api) and pilot_in_alliance(api) and account_active(api):
		insert_db('update pilots set keyid=?,vcode=? where email=?', [key, vcode, email])
		return render_template('services-success.html')
	else:
		return render_template('services-error.html')

def valid_pilot(email):
    results =  query_db('select keyid, vcode, id from pilots where email = ? limit 1',[email])

    #fail if no record for this address
    if len(results) != 1:
	return False

    #barf if the api and vcode have already been submitted
    if (results[0][0] or results[0][1]):
	return False

    return True

def valid_api(api):

    return True

def pilot_in_alliance(api):

    return True

def account_active(api):

    return True

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
