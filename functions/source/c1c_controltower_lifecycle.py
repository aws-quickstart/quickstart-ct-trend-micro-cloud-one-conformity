import time
import boto3
import json
import c1cconnectorapi
import ctlifecycleevent
import logging
import c1cresources
import cfnhelper

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_org_id():
    client = boto3.client("organizations")
    # TODO This assumes there is only one root... should we extend to support more?
    return client.list_roots()["Roots"][0]["ARN"].split(":")[4]


def create_cross_account_role(aws_account_id, c1c_connector):
    sts_session = assume_role(aws_account_id, c1cresources.ControlTowerRoleName)
    client = sts_session.client("iam")

    sts_client = sts_session.client("sts")
    sts_identity = sts_client.get_caller_identity()
    partition = sts_identity["Arn"].split(":")[1]

    logger.info(
        f"Creating role {c1cresources.IamRoleName} and policy {c1cresources.IamPolicyName} in account {aws_account_id}"
    )
    path = "/"
    try:
        logger.info("Creating role...")
        client.create_role(
            Path=path,
            RoleName=c1cresources.IamRoleName,
            AssumeRolePolicyDocument=c1cresources.get_assume_role_policy_document(
                c1c_connector
            ),
            Description="CloudOne Conformity Connector Role created by Control Tower",
        )
    except Exception as e:
        logger.error(f"Failed to create role: {e}")
        raise e
    try:
        logger.info("Creating and attaching policy parts...")
        c1c_policy_document = c1cresources.ConformityPolicyDoc()

        policy_part = 0
        for policy in c1c_policy_document.list_of_policies:
            policy_name = f"{c1cresources.IamPolicyName}{policy_part}"

            client.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy.get("document")),
            )
            # TODO this won't work if the partition is not aws.
            client.attach_role_policy(
                PolicyArn=f"arn:{partition}:iam::{aws_account_id}:policy/{policy_name}",
                RoleName=c1cresources.IamRoleName,
            )
            policy_part += 1
    except Exception as e:
        logger.error(f"Failed to attach policy: {e}")
        raise e
    else:
        return True


def delete_cross_account_role(aws_account_id):
    sts_session = assume_role(aws_account_id, c1cresources.ControlTowerRoleName)
    client = sts_session.client("iam")
    logger.info(f'Account is {boto3.client("sts").get_caller_identity()["Account"]}')

    # If we want to force deletion of stray policies, we can un-comment the STS client and
    # the policy_arns, then run a remove.

    # sts_client = sts_session.client("sts")
    # sts_identity = sts_client.get_caller_identity()
    # partition = sts_identity["Arn"].split(":")[1]

    policy_arns = [
        # f"arn:{partition}:iam::{aws_account_id}:policy/{c1cresources.IamPolicyName}{i}"
        # for i in ["0", "1", "2"]
    ]

    try:
        response = client.list_attached_role_policies(
            RoleName=c1cresources.IamRoleName,
        )

        policy_arns = [x["PolicyArn"] for x in response["AttachedPolicies"]]

        for arn in policy_arns:
            try:
                client.detach_role_policy(
                    RoleName=c1cresources.IamRoleName,
                    PolicyArn=arn,
                )
                logger.info(
                    f"Detached policy {arn} from role {c1cresources.IamRoleName}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to detach attached policy {arn} on role {c1cresources.IamRoleName} \
                        in account {aws_account_id}: {e}"
                )
    except Exception as e:
        logger.error(
            f"Failed to list attached role policies on role {c1cresources.IamRoleName} \
                in account {aws_account_id}: {e}"
        )

    for arn in policy_arns:
        try:
            client.delete_policy(
                PolicyArn=arn,
            )
            logger.info(f"Deleted policy {arn}")
        except Exception as e:
            logger.error(f"Failed to delete policy {arn}: {e}")

    try:
        client.delete_role(RoleName=c1cresources.IamRoleName)
        logger.info("Deleted role")
    except Exception as e:
        logger.error(
            f"Failed to delete role {c1cresources.IamRoleName} in account {aws_account_id}: {e}"
        )


def assume_role(aws_account_number, role_name) -> boto3.Session:
    try:
        sts_client = boto3.client("sts")
        logger.info(f"Retrieving session for operation")
        logger.info(
            f"currently executing in "
            f'{sts_client.get_caller_identity()["Account"]};'
            f" called account is {aws_account_number}"
        )
        if sts_client.get_caller_identity()["Account"] == aws_account_number:
            logger.info(
                f"Target account is Control Tower Management; returning local credentials session"
            )
            return boto3.session.Session()
        partition = sts_client.get_caller_identity()["Arn"].split(":")[1]

        assume_role_response = sts_client.assume_role(
            RoleArn="arn:{}:iam::{}:role/{}".format(
                partition, aws_account_number, role_name
            ),
            RoleSessionName=str(aws_account_number + "-" + role_name),
        )
        sts_session = boto3.Session(
            aws_access_key_id=assume_role_response["Credentials"]["AccessKeyId"],
            aws_secret_access_key=assume_role_response["Credentials"][
                "SecretAccessKey"
            ],
            aws_session_token=assume_role_response["Credentials"]["SessionToken"],
        )
        logger.info(f"Assumed session for {aws_account_number} - {role_name}.")
        return sts_session
    except Exception as e:
        logger.info(f"Could not assume role : {e}")
        raise e


def get_accounts():
    account_ids = []
    client = boto3.client("organizations")
    paginator = client.get_paginator("list_accounts")
    page_iterator = paginator.paginate()
    for page in page_iterator:
        for account in page.get("Accounts"):
            account_ids.append(account.get("Id"))
    return account_ids


def fresh_deploy(function_name):
    client = boto3.client("lambda")
    logger.info(f"Received function name {function_name} from context")
    count = 0
    for account_id in get_accounts():
        logger.info(f"Launched configure_account for {account_id}")
        client.invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps(
                {"InvokeAction": "configure_account", "account_id": account_id}
            ),
        )
        count += 1
    logger.info(f"Launched configure_account for {count} accounts")
    return None


def remove_all(function_name):
    client = boto3.client("lambda")
    logger.info(f"Received function name {function_name} from context")
    count = 0
    for account_id in get_accounts():
        logger.info(f"Launched remove_account_config for {account_id}")
        client.invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps(
                {"InvokeAction": "remove_account_config", "account_id": account_id}
            ),
        )
        count += 1
    logger.info(f"Launched remove_account_config for {count} accounts")
    return None


def update_accounts(function_name):
    client = boto3.client("lambda")
    logger.info(f"Received function name {function_name} from context")
    count = 0
    for account_id in get_accounts():
        logger.info(f"Launched update_account for {account_id}")
        client.invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps(
                {"InvokeAction": "update_account", "account_id": account_id}
            ),
        )
        count += 1
    logger.info(f"Launched update_accounts for {count} accounts")
    return None


def configure_account(aws_account_id):
    c1c_connector = c1cconnectorapi.CloudOneConformityConnector(
        c1cresources.get_api_key()
    )

    sts_client = boto3.client("sts")
    sts_identity = sts_client.get_caller_identity()
    partition = sts_identity["Arn"].split(":")[1]

    iam_client = boto3.client("iam")
    try:
        logger.info("Create Connector Object")
        logger.info("Create role in target account")
        create_cross_account_role(aws_account_id, c1c_connector)
    except iam_client.exceptions.EntityAlreadyExistsException as e:
        update_policy(aws_account_id)
    except Exception as e:
        logger.error(
            f"Failed to configure account {aws_account_id} with exception: {e}"
        )

    # Wait for eventual consistency to become consistent
    time.sleep(20)

    logger.info("Add account to Cloud One Conformity")

    try:
        return c1c_connector.add_account(
            f"arn:{partition}:iam::{aws_account_id}:role/{c1cresources.IamRoleName}"
        )
    except Exception as e:
        logger.error(f"Failed to add conformity connector with exception {e}")


def update_policy(aws_account_id):
    logger.info(f"Updating account {aws_account_id}")
    c1c_policy_document = c1cresources.ConformityPolicyDoc()
    sts_session = assume_role(aws_account_id, c1cresources.ControlTowerRoleName)

    sts_client = sts_session.client("sts")
    sts_identity = sts_client.get_caller_identity()
    partition = sts_identity["Arn"].split(":")[1]

    client = sts_session.client("iam")
    policy_resource = sts_session.resource("iam")
    logger.info(f"Updating policy in account {aws_account_id}")
    try:
        client.get_role(RoleName=c1cresources.IamRoleName)
    except client.exceptions.NoSuchEntityException:
        logger.info(f"Policy not found; configuring account")
        configure_account(aws_account_id)
        return

    logger.info(f"Updating AssumeRolePolicyDocument in account {aws_account_id}")
    try:
        c1c_connector = c1cconnectorapi.CloudOneConformityConnector(
            c1cresources.get_api_key()
        )
        client.update_assume_role_policy(
            RoleName=c1cresources.IamRoleName,
            PolicyDocument=c1cresources.get_assume_role_policy_document(c1c_connector),
        )
    except Exception as e:
        logger.error(f"Failed to update AssumeRolePolicyDocument: {e}")
        raise
    try:
        policy_part = 0
        # TODO this won't work if the partition is not aws.
        for policy in c1c_policy_document.list_of_policies:
            current_policy_object = policy_resource.Policy(
                f"arn:{partition}:iam::{aws_account_id}:policy/{c1cresources.IamPolicyName}{policy_part}"
            )
            current_policy_object_version = current_policy_object.default_version
            client.create_policy_version(
                PolicyArn=f"arn:{partition}:iam::{aws_account_id}:policy/{c1cresources.IamPolicyName}{policy_part}",
                PolicyDocument=json.dumps(policy.get("document")),
                SetAsDefault=True,
            )
            client.delete_policy_version(
                PolicyArn=f"arn:{partition}:iam::{aws_account_id}:policy/{c1cresources.IamPolicyName}{policy_part}",
                VersionId=current_policy_object_version.version_id,
            )
            policy_part += 1
    except Exception as e:
        logger.error(f"Failed to update policy {e}")
        raise


def remove_account_config(aws_account_id):
    try:
        c1c_connector = c1cconnectorapi.CloudOneConformityConnector(
            c1cresources.get_api_key()
        )
        logger.info(f"Removing account from conformity")
        c1c_connector.remove_account(aws_account_id)
        logger.info("Removing role from target account")
        delete_cross_account_role(aws_account_id)
    except Exception as e:
        logger.error(
            f"Failed to remove account {aws_account_id} config with exception: {e}"
        )


def lambda_handler(event, context):
    logger.info(f"Event received by handler: {event}")
    logger.info(
        f"function name: {context.function_name} "
        f"invoked arn: {context.invoked_function_arn}"
    )
    if "RequestType" in event:
        logger.info(f"Handling CloudFormation Request")
        if event["RequestType"] == "Create":
            logger.info(f"Received CloudFormation create")
            response = cfnhelper.cfnResponse(event, context)
            try:
                fresh_deploy(context.function_name)
            except Exception as e:
                logger.error(f"Failed to handle create event with exception: {e}")
                response.send(cfnhelper.responseCode.FAILED)
                return False
            response.send(cfnhelper.responseCode.SUCCESS)
        elif event["RequestType"] == "Update":
            logger.info(f"Received CloudFormation update")
            response = cfnhelper.cfnResponse(event, context)
            try:
                update_accounts(context.function_name)
            except Exception as e:
                logger.error(f"Failed to handle update event with exception: {e}")
                response.send(cfnhelper.responseCode.FAILED)
                return False
            response.send(cfnhelper.responseCode.SUCCESS)
        else:
            logger.warn(
                f"Ignoring unhandled CloudFormation request type: {event['RequestType']}"
            )
            response = cfnhelper.cfnResponse(event, context)
            response.send(cfnhelper.responseCode.SUCCESS)
    elif "InvokeAction" in event:
        try:
            if event["InvokeAction"] == "configure_account":
                configure_account(event["account_id"])
            elif event["InvokeAction"] == "update_account":
                update_policy(event["account_id"])
            elif event["InvokeAction"] == "remove_account_config":
                remove_account_config(event["account_id"])
            else:
                logger.warn(
                    f'Unrecognized InvokeAction {event["InvokeAction"]} -- try one of configure_account, update_account, remove_account_config, remove_all'
                )
            logger.info(f"Done")
        except Exception as e:
            logger.error(f"Failed to handle invoke action: {e}")
            return False
    else:
        try:
            life_cycle_event = ctlifecycleevent.LifeCycleEvent(event)
        except Exception as e:
            logger.warn(f"Did not find a supported event: {e}")
            return
        if life_cycle_event.create_account:
            try:
                configure_account(life_cycle_event.child_account_id)
            except Exception as e:
                logger.error(
                    f"Failed to handle create/update event from Control Tower: {e}"
                )
        elif life_cycle_event.remove_account:
            try:
                remove_account_config(life_cycle_event.child_account_id)
            except Exception as e:
                logger.error(f"Failed to handle remove event from Control Tower: {e}")
        else:
            logger.info(
                f"This is not an event handled by the integration. SKIPPING: {event}"
            )
            response = cfnhelper.cfnResponse(event, context)
            response.send(cfnhelper.responseCode.FAILED)
        return False
