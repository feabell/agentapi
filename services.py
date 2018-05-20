from flask import Flask, request, render_template, g, redirect, url_for, flash
import yaml

from services_util import *
from services_discord import get_invite_link
from services_slack import *
from preston.esi import Preston as ESIPreston

app = Flask(__name__)
app.config['PROPAGATE_EXCEPTIONS'] = True

config = yaml.load(open('services.conf', 'r'))
crest_config = yaml.load(open('crest_config.conf', 'r'))

auth_config = crest_config['agents']

preston = ESIPreston(
    user_agent=auth_config['EVE_OAUTH_USER_AGENT'],
    client_id=auth_config['EVE_OAUTH_CLIENT_ID'],
    client_secret=auth_config['EVE_OAUTH_SECRET'],
    callback_url=auth_config['EVE_OAUTH_CALLBACK'],
    scope=auth_config['EVE_OAUTH_SCOPE']
)

OAUTH2_CLIENT_SECRET = config['OAUTH2_CLIENT_SECRET']
SLACK_TOKEN = config['SLACK_TOKEN']

WDS_CORP_ID = "98330748"
ACADEMY_CORP_ID = "98415327"

app.config['BASIC_AUTH_USERNAME'] = config['BASIC_AUTH_USERNAME']
app.config['BASIC_AUTH_PASSWORD'] = config['BASIC_AUTH_PASSWORD']
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

from services_recruitment import services_recruitment
from services_discord import services_discord
from services_admin import services_admin
from services_torp import services_torp

app.register_blueprint(services_recruitment)
app.register_blueprint(services_discord)
app.register_blueprint(services_torp)
app.register_blueprint(services_admin, url_prefix='/admin')

@app.route('/', methods=['GET'])
def crest_landing():
  """
  Default landing page for services, with crest auth.
  """
  return render_template('services-landing-crest.html', show_crest=True, crest_url=preston.get_authorize_url())


@app.route('/', methods=['POST'])
def crest_update():
  email = request.form['email']
  token = request.form['token']

  #update the row with the users email address
  insert_db('UPDATE pilots set email = ?, active_account=1, in_alliance=1, slack_active=1 '
            'where token = ?',[email, token])

  #get additional info
  result = query_db('SELECT name from pilots where token = ?', [token])
  name = result[0][0]

  discord_invite_token = get_invite_link()
  slack_invite = invite_to_slack(email=email, name=name, token=SLACK_TOKEN)

  return render_template('services-success.html', token=discord_invite_token)

@app.route('/statsbot/callback', methods=['GET'])
def statsbot_callback():
  print(request.args['code'])
  return request.args['code']


@app.route('/auth/callback')
def crest_callback():
  """
  Process successfull crest authorisation attempts
  """
  # check response
  if 'error' in request.path:
      flash('There was an error in EVE\'s response', 'error')
      return url_for('services.crest_landing')
  try:
      auth = preston.authenticate(request.args['code'])
  except Exception as e:
      print('SSO callback exception: ' + str(e))
      flash('There was an authentication error signing you in.', 'error')
      return redirect(url_for('services.crest_landing'))

  pilot_info = auth.whoami()

  #pilot_id = pilot_info['CharacterId']
  pilot_name = pilot_info['CharacterName']
  pilot_id = pilot_info['CharacterID']
  pilot_corp = str(auth.characters(pilot_id).get('corporation_id'))
  refresh_token = auth.refresh_token  

  #pilot must be in corp
  if pilot_corp == WDS_CORP_ID or pilot_corp == ACADEMY_CORP_ID:
      #is the pilot an existing agent?
      result = query_db('SELECT name, email, token from pilots where lower(name) = ?', [pilot_name.lower()])
         
      if len(result) == 1:
        #existing pilot
        pilot_email = result[0]['email']
        
        if result[0]['token'] == None:
            #no refresh_token.  Update table and show message "Your account request has been processed"
            insert_db('UPDATE pilots set token = ?, in_alliance=1, active_account=1 where name = ?', [refresh_token, pilot_name])
            return render_template('services-crest_success.html', pilot_name=pilot_name, email=pilot_email, message="Your account has been successfully converted to ESI auth! No action by you is required :)")
        else:
            #pilot record is all updated, just show details and "Your slack and discord accounts are already active
            return render_template('services-crest_success.html', pilot_name=pilot_name, email=pilot_email, message="Your Slack and Discord accounts are already active")

      elif len(result) > 1:
        #could not uniquely identify pilot in DB
        flash('Multiple characters with your character name where identifed.  Please contact Dakodai to rectify.')
        return render_template('services-error.html')
      else:
        #new agent, insert a temp record to wait for the email
        insert_db('INSERT INTO pilots (name, token, in_alliance) values (?, ?, 1)', [pilot_name, refresh_token])
        return render_template('services-crest_process.html', pilot_name=pilot_name, pilot_id=pilot_id, token=refresh_token)

  else:
     #kick them out to the not-in-corp page
     print(pilot_name + "not in corp")
     flash('You aren\'t a member of WiNGSPAN Delivery Services')
     return render_template('services-error.html')

def default():
  """
  Default landing page for services.
  """
  return render_template('services-landing-esi.html')

'''
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
              'VALUES (?, ?, ?, ?, 1, 1, 1)', [email, name, key, vcode])
    print("[INFO] pilot {email} new account request success".format(email = email))
		
    discord_invite_token = get_invite_link()
    slack_invite = invite_to_slack(email=email, name=name, token=SLACK_TOKEN)

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
'''

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
