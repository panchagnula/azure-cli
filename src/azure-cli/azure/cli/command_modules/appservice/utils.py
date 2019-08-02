# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError


def str2bool(v):
    if v == 'true':
        retval = True
    elif v == 'false':
        retval = False
    else:
        retval = None
    return retval


def _normalize_sku(sku):
    sku = sku.upper()
    if sku == 'FREE':
        return 'F1'
    if sku == 'SHARED':
        return 'D1'
    return sku


def get_sku_name(tier):  # pylint: disable=too-many-return-statements
    tier = tier.upper()
    if tier in ['F1', 'FREE']:
        return 'FREE'
    if tier in ['D1', "SHARED"]:
        return 'SHARED'
    if tier in ['B1', 'B2', 'B3', 'BASIC']:
        return 'BASIC'
    if tier in ['S1', 'S2', 'S3']:
        return 'STANDARD'
    if tier in ['P1', 'P2', 'P3']:
        return 'PREMIUM'
    if tier in ['P1V2', 'P2V2', 'P3V2']:
        return 'PREMIUMV2'
    if tier in ['PC2', 'PC3', 'PC4']:
        return 'PremiumContainer'
    if tier in ['EP1', 'EP2', 'EP3']:
        return 'ElasticPremium'
    if tier in ['I1', 'I2', 'I3']:
        return 'Isolated'
    raise CLIError("Invalid sku(pricing tier), please refer to command help for valid values")


def _get_github_build_obj(stack):
    stack = stack.upper()
    if stack == 'PYTHON':
        return 'pip install -r requirements.txt'
    if stack == 'NODE':
        return 'npm install npm run build --if-present npm run test --if-present'
    return ''


def get_github_actions_yml(user, stack, name, type="app"):
    # type is used to differentiate if this simple app or container appß
    run_action_obj = _get_github_build_obj(stack)
    secrets_value = '${{{{secrets.{}{}PublishingProfile}}}}'.format(user, stack)
    if type == "app":
        workflow_dict = {
            'on': 'push',
            'jobs': {'build-and-deploy': {'runs-on': 'ubuntu-latest', 'steps': [{'uses': 'actions/checkout@master'},
                                                                                {'name': 'install, build, and test',
                                                                                 'run': run_action_obj},
                                                                                {'uses': 'azure/appservice-actions/'
                                                                                         'webapp@master',
                                                                                 'with': {'app-name': name,
                                                                                          'publish-profile': secrets_value
                                                                                          }}]}}}
    else: # assume it's container
        workflow_dict = {}
    return workflow_dict


def get_runtime_from_kind(kind, site_config_details):
    kind = kind.lower()
    if 'linux' in kind:
        return site_config_details.linux_fx_version
    # if kind == 'app':  # for windows webapps the kind is app
    return site_config_details.netFrameworkVersion
