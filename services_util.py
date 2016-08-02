import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime 
import sys 
import requests
import yaml
from flask import g

database = 'agentapi.db'

WDS_CORP_ID = "98330748"
ACADEMY_CORP_ID = "98415327"

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

      if corpID == WDS_CORP_ID:
        corp = corpID
        print("[INFO] pilot {name} is in WDS".format(name = pilotName))

      #if corpID == DSTA_CORP_ID and not corp:
      #  corp = corpID
      #  print("[INFO] pilot {name} is in DSTA".format(name = pilotName))

      if corpID == ACADEMY_CORP_ID and not corp:
        corp = corpID
        print("[INFO] pilot {name} is in WAEP".format(name = pilotName))

  except Exception as e:
    print("[WARN] barfed in XML api", sys.exc_info()[0])
    print(str(e))

  return corp



def pilot_in_alliance(key, vcode):
  """
  Method checks if pilot is in the alliance. Returns True/False
  """
  url = ('https://api.eveonline.com/account/Characters.xml.aspx?'
         'keyId={key}&vCode={vcode}'.format(key = key, vcode = vcode))
  #wdsAllianceID = "99005770"

  response = False	
  try:
    root = ET.fromstring(requests.get(url).content)

    #grab all of the pilots returned
    pilots = list(root.iter('row'))
		
    for pilot in pilots:
      corpID =  pilot.get('corporationID')
      pilotName = pilot.get('name')

      if corpID ==  WDS_CORP_ID or corpID == ACADEMY_CORP_ID:
        response = True
        print("[INFO] pilot {name} is in alliance".format(name = pilotName))

  except Exception as e:
    print("[WARN] barfed in XML api", sys.exc_info()[0])
    print( str(e))

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
  
  except Exception as e:
    print("[WARN] barfed in XML api", sys.exc_info()[0])
    print(str(e))
	
  return response

def in_alliance_and_active(email, keyid, vcode):
  """
  Method checks if the provided pilot is in corp and active.  If not active, returns their email address
  """
  if not (pilot_in_alliance(keyid, vcode) and account_active(keyid, vcode)):
    return email



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


