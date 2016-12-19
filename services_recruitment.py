from flask import Blueprint, render_template, url_for, request
import xml.etree.ElementTree as ET
import requests, sys, yaml
from services_util import *

services_recruitment = Blueprint('services_recruitment', __name__)
pre_reqs = yaml.load(open('pilot_prereqs.conf', 'r'))

base = pre_reqs['baseline']
sb = pre_reqs['sb']
strat = pre_reqs['strat']
astero = pre_reqs['astero']
recon = pre_reqs['recon']
blops = pre_reqs['blops']
amarr_t3 = pre_reqs['amarr_t3']
minmatar_t3 = pre_reqs['minmatar_t3']
caldari_t3 = pre_reqs['caldari_t3']
gallente_t3 = pre_reqs['gallente_t3']

RECRUITMENT_OPEN = pre_reqs['RECRUITMENT_OPEN']

@services_recruitment.route('/recruitment',  methods=['GET'])
@services_recruitment.route('/recruitment/',  methods=['GET'])
def rec_landing():
	return render_template('recruitment-landing.html', 
		base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero, 
		recon_prereq=recon, blops_prereq=blops, recruitment_open=RECRUITMENT_OPEN)

@services_recruitment.route('/recruitment',  methods=['POST'])
@services_recruitment.route('/recruitment/',  methods=['POST'])
def rec_process():
  """
  Landing for recruitment
  """
  
  #bail if recruitment is closed
  if not RECRUIMENT_OPEN:
   return redirect(url_for('services_recruitment.rec_landing'), code=302)

  name = request.form['name']
  key = request.form['key']
  vcode = request.form['vcode']
  blob = request.form['blob']

  #bail if submitted without correct info
  if not (key or vcode):
    return render_template('recruitment-apierror.html')
 
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
      for pilot in pilots:
        if pilot.get('characterID') == name:
          pilotID = int(pilot.get('characterID'))
          pilotName = pilot.get('name')
          print("pilot selected: " +pilotName)
    elif len(pilots) > 1 and not name:
      #get all the pilots
      player_pilots = {}
      for pilot in pilots:
        player_pilots[pilot.get('name')] = pilot.get('characterID')
         
      return render_template('recruitment-pickpilot.html', keyid=key, vcode=vcode, player_pilots=player_pilots, blob=blob)
    else:
      return render_template('recruitment-apierror.html')

    #check for duplicate active application
    result = query_db('SELECT name, status FROM recruits WHERE name=? AND status=0', [pilotName])
    if len(result) > 0:
        return render_template('recruitment-duplicate.html', pilotName=pilotName)

    skillsurl = ('https://api.eveonline.com/char/Skills.xml.aspx?'
		 'keyId={key}&vCode={vcode}&characterID={pilotID}'.format(key = key, vcode = vcode, pilotID = pilotID))

    pilotsskills = parse_skills(ET.fromstring(requests.get(skillsurl).content))

    base_met, baseneeded = check_skills(pilotsskills, base)
    sb_met, bomberneeded = check_skills(pilotsskills, sb)
    strat_met, stratneeded = check_skills(pilotsskills, strat)
    astero_met, asteroneeded = check_skills(pilotsskills, astero)
    recon_met, reconneeded = check_skills(pilotsskills, recon)
    blops_met, blopsneeded = check_skills(pilotsskills, blops)
    t3_met, t3needed = (check_skills(pilotsskills, amarr_t3) or check_skills(pilotsskills, gallente_t3) or check_skills(pilotsskills, minmatar_t3) or check_skills(pilotsskills, caldari_t3))

    skillsneeded = {
      'base': baseneeded,
      'bomber': bomberneeded,
      'strat': stratneeded,
      'astero': asteroneeded,
      'recon': reconneeded,
      'blops': blopsneeded
    }

    if base_met and (sb_met or strat_met or astero_met or recon_met or blops_met or t3_met):
      #insert a record to the recruitment table
      update_query = insert_db('INSERT INTO recruits '
                               '(name, keyid, vcode, blob, status, sb, astero, strat, recon, blops, t3, dateadded) '
                               ' VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, datetime())', 
                               [pilotName, key, vcode, blob, sb_met, astero_met, strat_met, recon_met, blops_met, t3_met])

      return render_template('recruitment-success.html', sb=sb_met, strat=strat_met, astero=astero_met, recon=recon_met, blops=blops_met, t3=t3_met)
    else:
      return render_template('recruitment-error.html', 
			pilotName=pilotName, sb=sb_met, strat=strat_met, astero=astero_met, recon=recon_met, blops=blops_met,
			base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero, 
			recon_prereq=recon, blops_prereq=blops, skillsneeded=skillsneeded)

  except Exception as e:
    print("[WARN] barfed in XML api", sys.exc_info()[0])
    print( str(e))

def check_skills(user_skills, req_skills): 
  met_req = True
  skills_not_met = {}

  for skill,level in req_skills.items():
    if not user_skills.get(skill):
      #print('not injected:'+skill)
      met_req = False
      skills_not_met[skill] = level
    elif user_skills.get(skill) >= level:
      #print('passed:'+skill)
      pass
    else:
      #print('failed:'+skill)
      met_req = False
      skills_not_met[skill] = level

  return met_req, skills_not_met

def parse_skills(xmltree):  

  skills = {}

  for skill in xmltree.iter('row'):
    skills[skill.get('typeName')] = int(skill.get('level'))

  return skills
