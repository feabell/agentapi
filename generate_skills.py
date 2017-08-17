import json
import sys
import requests


skill_category = 16

esi_base = "https://esi.tech.ccp.is/latest/universe/"
esi_trail =  "/?datasource=tranquility"

category_endpoint = esi_base + "categories/" + str(skill_category) + esi_trail

skills_map = {}

#iterate groups where category_id=16

for skillid in requests.get(category_endpoint).json()["groups"]:
	group_endpoint = esi_base + "groups/" + str(skillid) + esi_trail
	groups = requests.get(group_endpoint).json()
	print(groups["name"])
	print("=================================")

	for typeid in groups["types"]:
		type_endpoint = esi_base + "types/" +str(typeid) + esi_trail
		types = requests.get(type_endpoint).json()
		
		skills_map[typeid] = types["name"]
		#print(str(typeid) +"="+types["name"])


with open('skills_map.json', 'w') as fp:
	json.dump(skills_map, fp)


#for x,y in skills_map:
#	print(str(x) + ":" + y)


