import c1cconnectorapi
import boto3
from botocore.exceptions import ClientError
import base64
import logging
import json
import os

logger = logging.getLogger()

APIKEY_SECRET_ID = "TrendMicro/CloudOne/ConformityApiKey"
ControlTowerRoleName = "AWSControlTowerExecution"
CloudOneConformityAccountId = "717210094962"
IamRoleName = "CloudOneConformityConnectorRole"
IamPolicyName = "CloudOneConformityConnectorPolicy"


class ConformityPolicyDoc:
    def __init__(self):
        self.list_of_policies = []
        self.load_policy_parts()

    def load_policy_parts(self):
        with open("iam-policies.json", encoding="utf-8") as f:
            self.list_of_policies = json.load(f)

    def list_of_policies(self):
        return self.list_of_policies


def get_api_key():
    client = boto3.client("secretsmanager")
    try:
        get_secret_value_response = client.get_secret_value(SecretId=APIKEY_SECRET_ID)
    except ClientError as e:
        logger.error(f"Failed to retrieve secret: {e}")
        if e.response["Error"]["Code"] == "DecryptionFailureException":
            raise e
        elif e.response["Error"]["Code"] == "InternalServiceErrorException":
            raise e
        elif e.response["Error"]["Code"] == "InvalidParameterException":
            raise e
        elif e.response["Error"]["Code"] == "InvalidRequestException":
            raise e
        elif e.response["Error"]["Code"] == "ResourceNotFoundException":
            raise e
    else:
        if "SecretString" in get_secret_value_response:
            secret = json.loads(get_secret_value_response["SecretString"])["ApiKey"]
            return secret
        else:
            decoded_binary_secret = base64.b64decode(
                get_secret_value_response["SecretBinary"]
            )
            password = decoded_binary_secret.password
            return password


def get_assume_role_policy_document(c1c_connector):
    assume_role_policy_document = {
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Effect": "Allow",
                "Principal": {"AWS": CloudOneConformityAccountId},
                "Condition": {
                    "StringEquals": {"sts:ExternalId": c1c_connector.get_external_id()}
                },
                "Sid": "",
            }
        ],
        "Version": "2012-10-17",
    }
    return json.dumps(assume_role_policy_document)
