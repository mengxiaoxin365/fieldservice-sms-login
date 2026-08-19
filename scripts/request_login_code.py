import argparse
import uuid

from fieldservice_login.infrai_sms import InfraiSmsClient


parser = argparse.ArgumentParser(description="Send a technician login code")
parser.add_argument("phone_number", help="E.164 phone number")
args = parser.parse_args()

client = InfraiSmsClient()
client.request_code(args.phone_number, str(uuid.uuid4()))
print("code requested")
