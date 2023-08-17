import urllib3
import json
import logging
import os

logger = logging.getLogger()
GET = "GET"
POST = "POST"
DELETE = "DELETE"


class CloudOneConformityConnector:
    def __init__(self, api_key):
        self.base_url = "https://conformity.{region}.cloudone.trendmicro.com/api".format(
            region=os.environ["ConformityRegionEndpoint"]
        )
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/vnd.api+json",
            "Authorization": f"ApiKey {api_key}",
        }
        self.external_id = ""
        self.http = urllib3.PoolManager()

    def request(self, method, endpoint, body=None):
        if body is not None:
            body = bytes(json.dumps(body), encoding="utf-8")
        request_response = self.http.request(
            method, f"{self.base_url}{endpoint}", headers=self.headers, body=body
        )
        logger.info(
            f"http status for call to {endpoint} "
            f"was: {request_response.status} with response: {request_response.data}"
        )
        response = json.loads(request_response.data.decode("utf-8"))
        return response

    def create_external_id(self):
        return self.request(POST, "/external-ids")["data"]["id"]

    def get_external_id(self):
        self.external_id = self.request(GET, "/organisation/external-id")["data"]["id"]
        if self.external_id is None:
            self.external_id = self.create_external_id()
        return self.external_id

    def add_account(self, role_arn):
        body = {
            "data": {
                "type": "account",
                "attributes": {
                    "name": role_arn.split(":")[4],  # AWS account ID
                    "environment": "ControlTower",
                    "access": {
                        "keys": {"roleArn": role_arn, "externalId": self.external_id}
                    },
                    #"costPackage": False,
                    "hasRealTimeMonitoring": True,
                },
            }
        }
        return self.request(POST, "/accounts", body)

    def remove_account(self, aws_account_id):
        conformity_account_id = self.get_account_id(aws_account_id)
        if conformity_account_id is None:
            logger.info(
                f"No account found in Conformity for {aws_account_id}, skipping"
            )
            return None

        return self.request(DELETE, f"/accounts/{conformity_account_id}")

    def get_account_id(self, aws_account_id):
        try:
            all_accounts = self.request(GET, "/accounts")
            for account in all_accounts.get("data", []):
                if account.get("attributes").get("awsaccount-id") == aws_account_id:
                    logger.info(
                        "Found account id: "
                        + account.get("id")
                        + " for "
                        + aws_account_id
                    )
                    return account.get("id")
        except Exception as e:
            logger.error(f"could not get account ID from Conformity: {e}")
            raise e
