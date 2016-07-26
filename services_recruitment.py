from flask import Blueprint

services_recruitment = Blueprint('services_recruitment', __name__)

@services_recruitment.route('/recruitment')
def recruitment():
  """
  Landing for recruitment
  """
  return "Test"
