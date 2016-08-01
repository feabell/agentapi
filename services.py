from flask import Flask, request, render_template, g
import yaml

from services_util import *
from services_discord import get_invite_link

app = Flask(__name__)

config = yaml.load(open('services.conf', 'r'))

OAUTH2_CLIENT_SECRET = config['OAUTH2_CLIENT_SECRET']

app.config['BASIC_AUTH_USERNAME'] = config['BASIC_AUTH_USERNAME']
app.config['BASIC_AUTH_PASSWORD'] = config['BASIC_AUTH_PASSWORD']
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

from services_recruitment import services_recruitment
from services_discord import services_discord
from services_admin import services_admin

app.register_blueprint(services_recruitment)
app.register_blueprint(services_discord)
app.register_blueprint(services_admin, url_prefix='/admin')


@app.route('/')
def default():
  """
  Default landing page for services.
  """
  return render_template('services-landing.html')

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

@app.teardown_appcontext
def close_connection(exception):
  """
  Method ensures on __exit__ connection objects are garbage collected.
  """
  db = getattr(g, '_database', None)
  if db is not None:
    db.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, ssl_context='adhoc')
