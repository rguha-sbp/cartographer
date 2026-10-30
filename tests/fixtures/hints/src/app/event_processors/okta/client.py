import boto3
import requests
BASE = "https://example.okta.com/api/v1"
TOKEN_PARAM = "/app/okta/token"
ssm = boto3.client("ssm")


def users():
    token = ssm.get_parameter(Name="/app/okta/token")
    return requests.get(f"{BASE}/users", headers={"Authorization": token})
