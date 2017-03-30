from flask import render_template, Blueprint, url_for, redirect, request, session, flash
from flask.ext.basicauth import BasicAuth
from multiprocessing import Pool, Process
from preston.esi import Preston as ESIPreston
from urllib.parse import urlparse
import requests
import uuid

from services_util import *

names_url = 'https://esi.tech.ccp.is/latest/universe/names/?datasource=tranquility'

services_torp= Blueprint('services_torp', __name__)

config = yaml.load(open('services.conf', 'r'))
crest_config = yaml.load(open('crest_config.conf', 'r'))

create_crest_config = crest_config['torp_create']
join_crest_config = crest_config['torp_join']


create_preston = ESIPreston(
    user_agent=create_crest_config['EVE_OAUTH_USER_AGENT'],
    client_id=create_crest_config['EVE_OAUTH_CLIENT_ID'],
    client_secret=create_crest_config['EVE_OAUTH_SECRET'],
    callback_url=create_crest_config['EVE_OAUTH_CALLBACK'],
    scope=create_crest_config['EVE_OAUTH_SCOPE']
)

join_preston = ESIPreston(
    user_agent=join_crest_config['EVE_OAUTH_USER_AGENT'],
    client_id=join_crest_config['EVE_OAUTH_CLIENT_ID'],
    client_secret=join_crest_config['EVE_OAUTH_SECRET'],
    callback_url=join_crest_config['EVE_OAUTH_CALLBACK'],
    scope=join_crest_config['EVE_OAUTH_SCOPE']
)

SLACK_NPSI_TOKEN = config['SLACK_NPSI_TOKEN']

@services_torp.route('/npsi', methods = ['GET', 'POST'])
@services_torp.route('/npsi/', methods = ['GET', 'POST'])
def send_to_torpfleet():
  return redirect(url_for('npsi'))

@services_torp.route('/torpfleet', methods = ['GET', 'POST'])
@services_torp.route('/torpfleet/', methods = ['GET', 'POST'])
def npsi():
 """
 Form for sending Slack invites for the WDS BLOPS/NPSI community
 """
 if request.method == 'GET':
   return render_template('services-npsi-landing.html')
 elif request.method == 'POST':
   email = request.form['email']
   name = request.form['name']
   slack_invite = invite_to_slack(email=email, name=name, token=SLACK_NPSI_TOKEN)
   return render_template('services-npsi-success.html')

@services_torp.route('/torp/createfleet/', methods = ['GET','POST'])
def create_fleet():
  if request.method == 'GET':
    return render_template('services-npsi-createfleet.html', showcrest=True, crest_url=create_preston.get_authorize_url())
  elif request.method == 'POST':
    #grab form data
    fleeturl = request.form['fleeturl']
    session_id = session['id']

    if fleeturl == None or session_id == None:
      return redirect(url_for('services_torp.create_fleet'))

    #parse out the fleetid from fleeturl
    fleetid = urlparse(fleeturl).path.replace("/","")

    #update the db record
    update_query = update_db('UPDATE fleets set fleetid=? where sessionid=? ', [fleetid, session_id])

    #grab the fleetid
    fid = dict(query_db('SELECT id FROM fleets where sessionid=?', [session_id]), True)['id']

    if fid == None:
      return redirect(url_for('services_torp.create_fleet'))

    return render_template('services-npsi-createfleet.html', showcrest=False, fid=fid )

@services_torp.route('/torp/createfleet/callback')
def eve_create_oauth_callback():
   if 'error' in request.path:
     flash('There was an error in EVE\'s response', 'error')
     return redirect(url_for('services_torp.create_fleet'))
   
   try:
     auth = create_preston.authenticate(request.args['code'])
   except Exception as e:
        print('SSO callback exception: ' + str(e))
        flash('There was an authentication error signing you in.', 'error')
        return redirect(url_for('services_torp.create_fleet'))

   pilot_info = auth.whoami()
   pilot_name = pilot_info['CharacterName']
   refresh_token = auth.refresh_token
   
   #do some sessionid bullshit
   session_id = uuid.uuid4()
   session['id'] = session_id

   #check that the pilot is in our list of FC's

   #create a DB entry for this FC
   insert_query = insert_db('INSERT INTO fleets '
                            '(name, token, fleetid, dateadded, sessionid) '
                            'VALUES (?, ?, 0, datetime(), ?)',
                            [pilot_name, refresh_token, session_id])
   
   return render_template('services-npsi-createfleet.html', showcrest=False)


@services_torp.route('/torp/joinfleet', methods = ['GET'])
@services_torp.route('/torp/joinfleet/', methods = ['GET'])
@services_torp.route('/torp/joinfleet/<int:fid>', methods = ['GET'])
def join_fleet(fid):
  if fid == None:
    flash('No fleet specified.', 'error')
    return render_template('services-npsi-error.html')
 
  session['id'] = fid
    
  #lookup the fleetid, make sure it's valid
  fleet_query = query_db('select fleetid, token from fleets where id=?', [fid])

  if len(fleet_query) == 0: 
    flash('There is no active fleet with the specified ID.', 'error')
    return render_template('services-npsi-error.html')

  fleet = dict(fleet_query)

  #grab the fleetinfo from ESI
  refresh_token = fleet['token']
  fleetid = fleet['fleetid']
  
  if fleetid == 0: 
    flash('There is no active fleet with the specified ID.', 'error')
    return render_template('services-npsi-error.html')

  #check that the fleet is still good
  fcauth = create_preston.use_refresh_token(refresh_token)
  result = fcauth.fleets[fleetid]

  if result.get('error') is not None:
    flash('This fleet is no longer available.', 'error')
    return render_template('services-npsi-error.html')

  return render_template('services-npsi-joinfleet.html', showcrest=True, crest_url=join_preston.get_authorize_url())

@services_torp.route('/torp/joinfleet/callback')
def eve_join_oauth_callback():
  if 'error' in request.path:
    flash('There was an error in EVE\'s response', 'error')
    return url_for('services_torp.fleet_landing')
   
  try:
    auth = preston.authenticate(request.args['code'])
  except Exception as e:
    print('SSO callback exception: ' + str(e))
    flash('There was an authentication error signing you in.', 'error')
    return redirect(url_for('services_torp.fleet_landing'))

  pilot_info = auth.whoami()
  pilot_name = pilot_info['CharacterName']
  pilot_id = pilot_info['CharacterId']
  fid = session['id']
   
  #lookup the fleetid in db
  fleetid = dict(query_db('select fleetid, token from fleets where id=?', [fid], True))
  fleetid = fleet['fleetid'] 
  refresh_token = fleet['token']

  #grab the FC's token
  fcauth = create_preston.use_refresh_token(refresh_token)
  
  #send an invite
  data = {
   "character_id": pid,
   "role": "squad_member"
  }

  headers = {
   "Authorization":"Bearer {token}".format(token=refresh_token)
  }

  uri = 'https://esi.tech.ccp.is/latest/fleets/{fid}/members/'.format(fid = fleetid)
  requests.post(uri,data=data,headers=headers).json()

  return render_template('services-npsi-joinfleet.html', showcrest=False)
