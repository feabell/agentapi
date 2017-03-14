import json

from flask import Blueprint, render_template, url_for, request, flash, redirect
from preston.esi import Preston as ESIPreston

from services_util import *

names_url = 'https://esi.tech.ccp.is/latest/universe/names/?datasource=tranquility'

services_recruitment = Blueprint('services_recruitment', __name__)
pre_reqs = yaml.load(open('pilot_prereqs.conf', 'r'))
crest_config = yaml.load(open('crest_config.conf', 'r'))

preston = ESIPreston(
    user_agent=crest_config['EVE_OAUTH_USER_AGENT'],
    client_id=crest_config['EVE_OAUTH_CLIENT_ID'],
    client_secret=crest_config['EVE_OAUTH_SECRET'],
    callback_url=crest_config['EVE_OAUTH_CALLBACK'],
    scope=crest_config['EVE_OAUTH_SCOPE']
)

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
t3_all = {
  'legion': amarr_t3,
  'proteus': gallente_t3,
  'loki': minmatar_t3,
  'tengu': caldari_t3
}

RECRUITMENT_OPEN = pre_reqs['RECRUITMENT_OPEN']

@services_recruitment.route('/recruitment-old',  methods=['GET'])
@services_recruitment.route('/recruitment-old/',  methods=['GET'])
def rec_landing():

	return render_template('recruitment-landing.html', 
		base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero, 
		recon_prereq=recon, blops_prereq=blops, recruitment_open=RECRUITMENT_OPEN)

@services_recruitment.route('/recruitment-old',  methods=['POST'])
@services_recruitment.route('/recruitment-old/',  methods=['POST'])
def rec_process():
  """
  Landing for recruitment
  """
  
  #bail if recruitment is closed
  if not RECRUITMENT_OPEN:
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

    t3_needed = {
      'legion': {},
      'proteus': {},
      'loki': {},
      'tengu': {}
    }
    for race, t3_skills in t3_all.items():
      t3_met, t3_needed[race] = (check_skills(pilotsskills, t3_skills))
      if t3_met:
        break

    skillsneeded = {
      'base': baseneeded,
      'bomber': bomberneeded,
      'strat': stratneeded,
      'astero': asteroneeded,
      'recon': reconneeded,
      'blops': blopsneeded,
      't3': t3_needed.items()
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
			pilotName=pilotName, sb=sb_met, strat=strat_met, astero=astero_met, recon=recon_met, blops=blops_met, t3=t3_met,
			base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero, 
			recon_prereq=recon, blops_prereq=blops, skillsneeded=skillsneeded)

  except Exception as e:
    print("[WARN] barfed in XML api", sys.exc_info()[0])
    print( str(e))


@services_recruitment.route('/recruitment', methods=['GET'])
@services_recruitment.route('/recruitment/', methods=['GET'])
def crest_landing():
    return render_template('recruitment-landing.html',
                           base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero,
                           recon_prereq=recon, blops_prereq=blops, recruitment_open=RECRUITMENT_OPEN, show_crest=True,
                           crest_url=preston.get_authorize_url())


@services_recruitment.route('/recruitment', methods=['POST'])
@services_recruitment.route('/recruitment/', methods=['POST'])
def crest_process():
    # Get pilot name from form
    pilot_name = request.form['name']
    blob = request.form['blob']

    # Get refresh token from db to fetch skills
    refresh_token = dict(query_db('SELECT * FROM recruits WHERE name=?', [pilot_name], True))['token']

    auth = preston.use_refresh_token(refresh_token)

    pilot_info = auth.whoami()

    try:
        # fetch skills
        result = auth.characters[pilot_info['CharacterID']].skills()
        if result.get('error') is not None:
            flash('ESI is not responding. Please try again, or wait a few minutes.', 'error')
            return render_template('recruitment-landing.html',
                                   base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero,
                                   recon_prereq=recon, blops_prereq=blops, recruitment_open=RECRUITMENT_OPEN,
                                   show_crest=False,
                                   crest_auth=True, name=pilot_name)

        skills = result['skills']
        skills_dict = {}
        ids_list = []
        for skill in skills:
            ids_list.append(skill.get('skill_id'))

        skill_names = requests.post(url=names_url, json=ids_list).json()

        for skill in skills:
            skill_id = skill['skill_id']
            skill_name = next(item['name'] for item in skill_names if item['id'] == skill_id)
            skill_level_trained = skill['current_skill_level']
            skills_dict[skill_name] = skill_level_trained

        base_met, baseneeded = check_skills(skills_dict, base)
        sb_met, bomberneeded = check_skills(skills_dict, sb)
        strat_met, stratneeded = check_skills(skills_dict, strat)
        astero_met, asteroneeded = check_skills(skills_dict, astero)
        recon_met, reconneeded = check_skills(skills_dict, recon)
        blops_met, blopsneeded = check_skills(skills_dict, blops)

        t3_needed = {
            'legion': {},
            'proteus': {},
            'loki': {},
            'tengu': {}
        }
        for race, t3_skills in t3_all.items():
            t3_met, t3_needed[race] = (check_skills(skills_dict, t3_skills))
            if t3_met:
                break

        skillsneeded = {
            'base': baseneeded,
            'bomber': bomberneeded,
            'strat': stratneeded,
            'astero': asteroneeded,
            'recon': reconneeded,
            'blops': blopsneeded,
            't3': t3_needed.items()
        }

        if base_met and (sb_met or strat_met or astero_met or recon_met or blops_met or t3_met):
            update_query = insert_db('UPDATE recruits '
                                     'SET blob=?, status=0, sb=?, astero=?, strat=?, recon=?, blops=?, t3=?, dateadded=datetime(), token=? '
                                     ' WHERE name=?',
                                     [blob, sb_met, astero_met, strat_met, recon_met, blops_met,
                                      t3_met, refresh_token, pilot_name])
            return render_template('recruitment-success.html', sb=sb_met, strat=strat_met, astero=astero_met,
                                   recon=recon_met, blops=blops_met, t3=t3_met)
        else:
            return render_template('recruitment-error.html',
                                   pilotName=pilot_name, sb=sb_met, strat=strat_met, astero=astero_met, recon=recon_met,
                                   blops=blops_met, t3=t3_met,
                                   base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero,
                                   recon_prereq=recon, blops_prereq=blops, skillsneeded=skillsneeded)

    except Exception as e:
        print('Error processing skills: ' + str(e))
        flash('There was an error fetching data.', 'error')
        return render_template('recruitment-landing.html',
                               base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero,
                               recon_prereq=recon, blops_prereq=blops, recruitment_open=RECRUITMENT_OPEN,
                               show_crest=False,
                               crest_auth=True, name=pilot_name)


@services_recruitment.route('/eve/callback')
def eve_oauth_callback():
    # check response
    if 'error' in request.path:
        flash('There was an error in EVE\'s response', 'error')
        return url_for('services_recruitment.crest_landing')
    try:
        auth = preston.authenticate(request.args['code'])
    except Exception as e:
        print('SSO callback exception: ' + str(e))
        flash('There was an authentication error signing you in.', 'error')
        return redirect(url_for('services_recruitment.crest_landing'))

    pilot_info = auth.whoami()
    pilot_name = pilot_info['CharacterName']
    refresh_token = auth.refresh_token

    # check for duplicate active application
    result = query_db('SELECT name, status FROM recruits WHERE name=? AND status>=0 AND status <3', [pilot_name])
    if len(result) > 0:
        return render_template('recruitment-duplicate.html', pilotName=pilot_name)

    # check for duplicate tokens
    token_exists = query_db('SELECT name, token FROM recruits WHERE NAME=?', [pilot_name])

    if len(token_exists) == 0:
        insert_query = insert_db('INSERT INTO recruits '
                                 '(name, token, blob, status, dateadded) '
                                 'VALUES (?, ?, ?, -1, datetime())',
                                 [pilot_name, refresh_token, 'INCOMPLETE APPLICATION'])
    else:
        update_query = insert_db('UPDATE recruits '
                                 'SET token=?, blob=?, dateadded=datetime(), status=-1 '
                                 'WHERE name=?',
                                 [refresh_token, 'INCOMPLETE APPLICATION', pilot_name])

    flash('Logged in as: ' + pilot_name, 'success')

    return render_template('recruitment-landing.html',
                           base_prereq=base, sb_prereq=sb, strat_prereq=strat, ast_prereq=astero,
                           recon_prereq=recon, blops_prereq=blops, recruitment_open=RECRUITMENT_OPEN, show_crest=False,
                           crest_auth=True, name=pilot_name)


@services_recruitment.route('/recruitment/view/<pilot_name>')
def view_recruit(pilot_name):
    try:
        # prefer token/ESI method
        query = dict(query_db('SELECT * FROM recruits WHERE name=?', [pilot_name], True))
        refresh_token = query['token']
        blob = query['blob']

        skill_groups = json.load(open('skill_groups.json', 'r'))

        skills_dict = {}
        skills_stats = {}

        # XML fallback
        if refresh_token is None:
            result = dict(query_db('SELECT * FROM recruits WHERE name=?', [pilot_name], True))
            key = result['keyid']
            vcode = result['vcode']

            url = ('https://api.eveonline.com/account/Characters.xml.aspx?'
                   'keyId={key}&vCode={vcode}'.format(key=key, vcode=vcode))
            pilotID = ''

            root = ET.fromstring(requests.get(url).content)

            # grab all of the pilots returned
            pilots = list(root.iter('row'))

            if len(pilots) == 1:
                pilotID = pilots[0].get('characterID')
            elif len(pilots) > 1:
                for pilot in pilots:
                    if pilot.get('name') == pilot_name:
                        pilotID = int(pilot.get('characterID'))

            skillsurl = ('https://api.eveonline.com/char/Skills.xml.aspx?'
                         'keyId={key}&vCode={vcode}&characterID={pilotID}'.format(key=key, vcode=vcode, pilotID=pilotID))
            result = ET.fromstring(requests.get(skillsurl).content)

            # Format the dicts/lists the same way as ESI does to reuse parsing code
            skills = []
            skill_names = []
            for skill in result.iter('row'):
                skills.append({
                    'skillpoints_in_skill': int(skill.get('skillpoints')),
                    'skill_id': int(skill.get('typeID')),
                    'current_skill_level': int(skill.get('level'))
                })
                skill_names.append({
                    'id': int(skill.get('typeID')),
                    'name': skill.get('typeName')
                })

        # We have an ESI token
        else:
            # get new access token from our stored refresh token
            auth = preston.use_refresh_token(refresh_token)

            pilot_info = auth.whoami()
            pilotID = pilot_info['CharacterID']

            result = auth.characters[pilotID].skills()
            if result.get('error') is not None:
                flash('ESI is not responding. Please try again, or wait a few minutes.', 'error')
                return render_template('recruitment-view.html')

            skills = result['skills']

            # Prepare and get names form the skill ids
            ids_list = []
            for skill in skills:
                ids_list.append(skill.get('skill_id'))

            try:
                skill_names = requests.post(url=names_url, json=ids_list).json()

            except Exception as e:
                flash('There was an error in EVE\'s response', 'error')
                print('SSO callback exception: ' + str(e))
                return render_template('recruitment-view.html')

    except Exception as e:
        flash('Pilot not found', 'error')
        print('Error: ' + str(e))
        return render_template('recruitment-view.html')

    skills_stats['Totals'] = {}
    skills_stats['Totals']['num_skills'] = len(skills)
    skills_stats['Totals']['total_sp'] = 0

    # Parse skills into dicts for the html response
    try:
        for group, child_skills in skill_groups.items():
            for skill in skills:
                if skill['skill_id'] in child_skills:
                    # Prevents dict errors by setting child items to {} first
                    if group not in skills_dict:
                        skills_dict[group] = {}
                        skills_stats[group] = {}
                        skills_stats[group]['skills_in_group'] = 0
                        skills_stats[group]['sp_in_group'] = 0

                    # Add skill and metadata to dicts
                    skill_id = skill['skill_id']
                    skill_name = next(item['name'] for item in skill_names if item['id'] == skill_id)  # stackoverflow FTW
                    skill_level_trained = skill['current_skill_level']
                    skills_dict[group][skill_name] = skill_level_trained
                    skills_stats[group]['skills_in_group'] += 1
                    skills_stats[group]['sp_in_group'] += skill['skillpoints_in_skill']
                    skills_stats['Totals']['total_sp'] += skill['skillpoints_in_skill']

    except Exception as e:
        flash('There was an error parsing skills', 'error')
        print('Skill Parse error: ' + str(e))
        return render_template('recruitment-view.html')

    return render_template('recruitment-view.html', pilot_name=pilot_name, pilotID=pilotID, skills=skills_dict,
                           skills_stats=skills_stats, blob=blob)


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
