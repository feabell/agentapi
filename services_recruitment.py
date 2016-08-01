from flask import Blueprint, render_template, url_for, request
import xml.etree.ElementTree as ET
import requests, sys
from services_util import *

services_recruitment = Blueprint('services_recruitment', __name__)

@services_recruitment.route('/recruitment',  methods=['GET'])
@services_recruitment.route('/recruitment/',  methods=['GET'])
def rec_landing():
	return render_template('recruitment-landing.html')

@services_recruitment.route('/recruitment',  methods=['POST'])
@services_recruitment.route('/recruitment/',  methods=['POST'])
def rec_process():
  """
  Landing for recruitment
  """
  name = request.form['name']
  key = request.form['key']
  vcode = request.form['vcode']
  blob = request.form['blob']

  #bail if submitted without correct info
  if not (key or vcode):
    return render_template('recruitment-error.html')
 
  url = ('https://api.eveonline.com/account/Characters.xml.aspx?'
         'keyId={key}&vCode={vcode}'.format(key = key, vcode = vcode))
  pilotID=''

  try:
    root = ET.fromstring(requests.get(url).content)

    #grab all of the pilots returned
    pilots = list(root.iter('row'))

    if len(pilots) == 1:
      pilotID = pilots[0].get('characterID')
      pilotName = pilots[0].get('name')
    elif len(pilots) > 1 and name:
      print("pilot selected")
      for pilot in pilots:
        if pilot.get('characterID') == name:
          pilotID = int(pilot.get('characterID'))
          pilotName = pilot.get('name')
          print(pilotName)
    elif len(pilots) > 1 and not name:
      print ("multi pilots")
      #get all the pilots
      player_pilots = {}
      for pilot in pilots:
        player_pilots[pilot.get('name')] = pilot.get('characterID')
         
      return render_template('recruitment-pickpilot.html', keyid=key, vcode=vcode, player_pilots=player_pilots, blob=blob)
    else:
      return render_template('recruitment-error.html')

    skillsurl = ('https://api.eveonline.com/char/Skills.xml.aspx?'
		 'keyId={key}&vCode={vcode}&characterID={pilotID}'.format(key = key, vcode = vcode, pilotID = pilotID))

    pilotsskills = parse_skills(ET.fromstring(requests.get(skillsurl).content))

    baseline = {'Astrometrics': 4,
	'Astrometric Acquisition': 2,
	'Astrometric Pinpointing': 2,
	'Astrometric Rangefinding': 2,
	'Cloaking': 4,
	'Warp Drive Operation': 3,
	'Signature Analysis': 3}

    sb = {'Torpedoes': 4,
	'Missile Launcher Operation': 5,
	'Guided Missile Precision': 2,
	'Weapon Upgrades': 4,
	'Target Navigation Prediction': 2,
	'Covert Ops': 4,
	'Missile Bombardment': 4}

    strat = {'Amarr Cruiser' : 4,
	'Gallente Cruiser': 4,
	'Hull Upgrades' : 4,
	'Mechanics' : 5,
	'Capacitor Emission Systems': 4,
	'Light Drone Operation': 4,
	'Medium Drone Operation':  4,
	'Heavy Drone Operation': 4,
	'Drones' : 5,
	'Drone Interfacing' : 4,
	'Drone Sharpshooting': 4}

    astero = {'Amarr Frigate': 4,
	'Gallente Frigate': 4,
	'Light Drone Operation' : 4,
	'Drones': 5,
	'Drone Interfacing' : 4,
	'Propulsion Jamming' : 4,
	'Astrometric Acquisition': 4,
	'Astrometric Pinpointing': 4,
	'Astrometric Rangefinding': 4}

    recon = {'Recon Ships' : 4,
	'Power Grid Management': 5,
	'Navigation': 5,
	'Propulsion Jamming': 4 } 

    blops = {'Black Ops': 4,
	'Jump Fuel Conservation': 4,
	'Propulsion Jamming': 3}

    amarr_t3 = {'Amarr Defensive Systems': 4,
	'Amarr Electronic Systems': 4,
	'Amarr Offensive Systems': 4,
	'Amarr Propulsion Systems': 4,
	'Amarr Engineering Systems': 4,
        'Amarr Strategic Cruiser': 3 }

    gallente_t3 = {'Gallente Defensive Systems': 4,
	'Gallente Electronic Systems': 4,
	'Gallente Offensive Systems': 4,
	'Gallente Propulsion Systems': 4,
	'Gallente Engineering Systems': 4,
        'Gallente Strategic Cruiser': 3 }

    minmatar_t3 = {'Minmatar Defensive Systems': 4,
	'Minmatar Electronic Systems': 4,
	'Minmatar Offensive Systems': 4,
	'Minmatar Propulsion Systems': 4,
	'Minmatar Engineering Systems': 4,
        'Minmatar Strategic Cruiser': 3 }
    
    caldari_t3 = {'Caldari Defensive Systems': 4,
	'Caldari Electronic Systems': 4,
	'Caldari Offensive Systems': 4,
	'Caldari Propulsion Systems': 4,
	'Caldari Engineering Systems': 4,
        'Caldari Strategic Cruiser': 3 }

    base_met = check_skills(pilotsskills, baseline)
    sb_met = check_skills(pilotsskills, sb)
    strat_met = check_skills(pilotsskills, strat)
    astero_met = check_skills(pilotsskills, astero)
    recon_met = check_skills(pilotsskills, recon)
    blops_met = check_skills(pilotsskills, blops)
    t3_met = (check_skills(pilotsskills, amarr_t3) or check_skills(pilotsskills, gallente_t3) or check_skills(pilotsskills, minmatar_t3) or check_skills(pilotsskills, caldari_t3))

    if base_met and (sb_met or strat_met or astero_met or recon_met or blops_met or t3_met):
      #insert a record to the recruitment table
      update_query = insert_db('INSERT INTO recruits '
                               '(name, keyid, vcode, blob, status, sb, astero, strat, recon, blops, t3) '
                               ' VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)', 
                               [pilotName, key, vcode, blob, sb_met, astero_met, strat_met, recon_met, blops_met, t3_met])

      return render_template('recruitment-success.html', sb=sb_met, strat=strat_met, astero=astero_met, recon=recon_met, blops=blops_met, t3=t3_met)
    else:
      return render_template('recruitment-fail.html', sb=sb_met, strat=strat_met, astero=astero_met, recon=recon_met, blops=blops_met)

  except Exception as e:
    print("[WARN] barfed in XML api", sys.exc_info()[0])
    print( str(e))

def check_skills(user_skills, req_skills): 
  met_req = True 

  for skill,level in req_skills.items():
    if not user_skills.get(skill):
      print('not injected:'+skill)
      met_req = False
    elif user_skills.get(skill) >= level:
      print('passed:'+skill)
    else:
      print('failed:'+skill)
      met_req = False

  return met_req

def parse_skills(xmltree):  

  skills = {}

  for skill in xmltree.iter('row'):
    skills[skill.get('typeName')] = int(skill.get('level'))

  return skills
