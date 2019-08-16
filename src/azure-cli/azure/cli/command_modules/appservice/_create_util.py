# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
import os
import zipfile
from azure.cli.core.commands.client_factory import get_mgmt_service_client
from azure.mgmt.resource.resources.models import ResourceGroup
from ._constants import (NETCORE_VERSION_DEFAULT, NETCORE_VERSIONS, NODE_VERSION_DEFAULT,
                         NODE_VERSIONS, NETCORE_RUNTIME_NAME, NODE_RUNTIME_NAME, DOTNET_RUNTIME_NAME,
                         DOTNET_VERSION_DEFAULT, DOTNET_VERSIONS, STATIC_RUNTIME_NAME,
                         PYTHON_RUNTIME_NAME, PYTHON_VERSION_DEFAULT, LINUX_SKU_DEFAULT, OS_DEFAULT)

logger = get_logger(__name__)


def _resource_client_factory(cli_ctx, **_):
    from azure.cli.core.profiles import ResourceType
    return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_RESOURCE_RESOURCES)


def web_client_factory(cli_ctx, **_):
    from azure.mgmt.web import WebSiteManagementClient
    return get_mgmt_service_client(cli_ctx, WebSiteManagementClient)


def zip_contents_from_dir(dirPath, lang):
    relroot = os.path.abspath(os.path.join(dirPath, os.pardir))
    path_and_file = os.path.splitdrive(dirPath)[1]
    file_val = os.path.split(path_and_file)[1]
    zip_file_path = relroot + os.path.sep + file_val + ".zip"
    abs_src = os.path.abspath(dirPath)
    with zipfile.ZipFile("{}".format(zip_file_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for dirname, subdirs, files in os.walk(dirPath):
            # skip node_modules folder for Node apps,
            # since zip_deployment will perfom the build operation
            if lang.lower() == NODE_RUNTIME_NAME and 'node_modules' in subdirs:
                subdirs.remove('node_modules')
            elif lang.lower() == NETCORE_RUNTIME_NAME:
                if 'bin' in subdirs:
                    subdirs.remove('bin')
                elif 'obj' in subdirs:
                    subdirs.remove('obj')
            for filename in files:
                absname = os.path.abspath(os.path.join(dirname, filename))
                arcname = absname[len(abs_src) + 1:]
                zf.write(absname, arcname)
    return zip_file_path


def get_runtime_version_details(file_path, lang_name):
    version_detected = None
    version_to_create = None
    if lang_name.lower() == NETCORE_RUNTIME_NAME:
        # method returns list in DESC, pick the first
        version_detected = parse_netcore_version(file_path)[0]
        version_to_create = detect_netcore_version_tocreate(version_detected)
    elif lang_name.lower() == DOTNET_RUNTIME_NAME:
        # method returns list in DESC, pick the first
        version_detected = parse_dotnet_version(file_path)
        version_to_create = detect_dotnet_version_tocreate(version_detected)
    elif lang_name.lower() == NODE_RUNTIME_NAME:
        if file_path == '':
            version_detected = "-"
            version_to_create = NODE_VERSION_DEFAULT
        else:
            version_detected = parse_node_version(file_path)[0]
            version_to_create = detect_node_version_tocreate(version_detected)
    elif lang_name.lower() == PYTHON_RUNTIME_NAME:
        version_detected = "-"
        version_to_create = PYTHON_VERSION_DEFAULT
    elif lang_name.lower() == STATIC_RUNTIME_NAME:
        version_detected = "-"
        version_to_create = "-"
    return {'detected': version_detected, 'to_create': version_to_create}


def create_resource_group(cmd, rg_name, location):
    rcf = _resource_client_factory(cmd.cli_ctx)
    rg_params = ResourceGroup(location=location)
    return rcf.resource_groups.create_or_update(rg_name, rg_params)


def _check_resource_group_exists(cmd, rg_name):
    rcf = _resource_client_factory(cmd.cli_ctx)
    return rcf.resource_groups.check_existence(rg_name)


def _check_resource_group_supports_os(cmd, rg_name, is_linux):
    # get all appservice plans from RG
    client = web_client_factory(cmd.cli_ctx)
    plans = list(client.app_service_plans.list_by_resource_group(rg_name))
    for item in plans:
        # for Linux if an app with reserved==False exists, ASP doesn't support Linux
        if is_linux and not item.reserved:
            return False
        if not is_linux and item.reserved:
            return False
    return True


def get_num_apps_in_asp(cmd, rg_name, asp_name):
    client = web_client_factory(cmd.cli_ctx)
    return len(list(client.app_service_plans.list_web_apps(rg_name, asp_name)))


# pylint:disable=unexpected-keyword-arg
def get_lang_from_content(src_path):
    # NODE: package.json should exist in the application root dir
    # NETCORE & DOTNET: *.csproj should exist in the application dir
    # NETCORE: <TargetFramework>netcoreapp2.0</TargetFramework>
    # DOTNET: <TargetFrameworkVersion>v4.5.2</TargetFrameworkVersion>
    runtime_details_dict = dict.fromkeys(['language', 'file_loc', 'default_sku'])
    package_json_file = os.path.join(src_path, 'package.json')
    package_python_file = os.path.join(src_path, 'requirements.txt')
    package_netcore_file = ""
    static_html_file = ""
    runtime_details_dict['language'] = NETCORE_RUNTIME_NAME  # default to windows
    runtime_details_dict['file_loc'] = ''
    runtime_details_dict['default_sku'] = 'F1'
    import fnmatch
    for _dirpath, _dirnames, files in os.walk(src_path):
        for file in files:
            if fnmatch.fnmatch(file, "*.csproj"):
                package_netcore_file = os.path.join(src_path, file)
                break
            if fnmatch.fnmatch(file, "*.html"):
                static_html_file = os.path.join(src_path, file)
                break

    if os.path.isfile(package_python_file):
        runtime_details_dict['language'] = PYTHON_RUNTIME_NAME
        runtime_details_dict['file_loc'] = package_python_file
        runtime_details_dict['default_sku'] = LINUX_SKU_DEFAULT
    elif os.path.isfile(package_json_file) or os.path.isfile('server.js') or os.path.isfile('index.js'):
        runtime_details_dict['language'] = NODE_RUNTIME_NAME
        runtime_details_dict['file_loc'] = package_json_file if os.path.isfile(package_json_file) else ''
        runtime_details_dict['default_sku'] = LINUX_SKU_DEFAULT
    elif package_netcore_file:
        runtime_lang = detect_dotnet_lang(package_netcore_file)
        runtime_details_dict['language'] = runtime_lang
        runtime_details_dict['file_loc'] = package_netcore_file
        runtime_details_dict['default_sku'] = 'F1'
    elif static_html_file:
        runtime_details_dict['language'] = STATIC_RUNTIME_NAME
        runtime_details_dict['file_loc'] = static_html_file
        runtime_details_dict['default_sku'] = 'F1'
    return runtime_details_dict


def detect_dotnet_lang(csproj_path):
    import xml.etree.ElementTree as ET
    import re
    parsed_file = ET.parse(csproj_path)
    root = parsed_file.getroot()
    version_lang = ''
    for target_ver in root.iter('TargetFramework'):
        version_lang = re.sub(r'([^a-zA-Z\s]+?)', '', target_ver.text)
    if 'netcore' in version_lang.lower():
        return NETCORE_RUNTIME_NAME
    return DOTNET_RUNTIME_NAME


def parse_dotnet_version(file_path):
    version_detected = ['4.7']
    try:
        from xml.dom import minidom
        import re
        xmldoc = minidom.parse(file_path)
        framework_ver = xmldoc.getElementsByTagName('TargetFrameworkVersion')
        target_ver = framework_ver[0].firstChild.data
        non_decimal = re.compile(r'[^\d.]+')
        # reduce the version to '5.7.4' from '5.7'
        if target_ver is not None:
            # remove the string from the beginning of the version value
            c = non_decimal.sub('', target_ver)
            version_detected = c[:3]
    except:  # pylint: disable=bare-except
        version_detected = version_detected[0]
    return version_detected


def parse_netcore_version(file_path):
    import xml.etree.ElementTree as ET
    import re
    version_detected = ['0.0']
    parsed_file = ET.parse(file_path)
    root = parsed_file.getroot()
    for target_ver in root.iter('TargetFramework'):
        version_detected = re.findall(r"\d+\.\d+", target_ver.text)
    # incase of multiple versions detected, return list in descending order
    version_detected = sorted(version_detected, key=float, reverse=True)
    return version_detected


def parse_node_version(file_path):
    # from node experts the node value in package.json can be found here   "engines": { "node":  ">=10.6.0"}
    import json
    import re
    version_detected = []
    with open(file_path) as data_file:
        data = json.load(data_file)
        for key, value in data.items():
            if key == 'engines' and 'node' in value:
                value_detected = value['node']
                non_decimal = re.compile(r'[^\d.]+')
                # remove the string ~ or  > that sometimes exists in version value
                c = non_decimal.sub('', value_detected)
                # reduce the version to '6.0' from '6.0.0'
                if '.' in c:  # handle version set as 4 instead of 4.0
                    num_array = c.split('.')
                    num = num_array[0] + "." + num_array[1]
                else:
                    num = c + ".0"
                version_detected.append(num)
    return version_detected or ['0.0']


def detect_netcore_version_tocreate(detected_ver):
    if detected_ver in NETCORE_VERSIONS:
        return detected_ver
    return NETCORE_VERSION_DEFAULT


def detect_dotnet_version_tocreate(detected_ver):
    min_ver = DOTNET_VERSIONS[0]
    if detected_ver in DOTNET_VERSIONS:
        return detected_ver
    if detected_ver < min_ver:
        return min_ver
    return DOTNET_VERSION_DEFAULT


def detect_node_version_tocreate(detected_ver):
    if detected_ver in NODE_VERSIONS:
        return detected_ver
    # get major version & get the closest version from supported list
    major_ver = int(detected_ver.split('.')[0])
    node_ver = NODE_VERSION_DEFAULT
    if major_ver < 4:
        node_ver = NODE_VERSION_DEFAULT
    elif major_ver >= 4 and major_ver < 6:
        node_ver = '4.5'
    elif major_ver >= 6 and major_ver < 8:
        node_ver = '6.9'
    elif major_ver >= 8 and major_ver < 10:
        node_ver = NODE_VERSION_DEFAULT
    elif major_ver >= 10:
        node_ver = '10.14'
    return node_ver


def find_key_in_json(json_data, key):
    for k, v in json_data.items():
        if key in k:
            yield v
        elif isinstance(v, dict):
            for id_val in find_key_in_json(v, key):
                yield id_val


def set_location(cmd, sku, location):
    client = web_client_factory(cmd.cli_ctx)
    if location is None:
        locs = client.list_geo_regions(sku, True)
        available_locs = []
        for loc in locs:
            available_locs.append(loc.name)
        loc = available_locs[0]
    else:
        loc = location
    return loc.replace(" ", "").lower()


# check if the RG value to use already exists and follows the OS requirements or new RG to be created
def should_create_new_rg(cmd, rg_name, is_linux):
    if (_check_resource_group_exists(cmd, rg_name) and
            _check_resource_group_supports_os(cmd, rg_name, is_linux)):
        return False
    return True


def does_app_already_exist(cmd, name):
    """ This is used by az webapp up to verify if a site needs to be created or should just be deployed"""
    client = web_client_factory(cmd.cli_ctx)
    site_availability = client.check_name_availability(name, 'Microsoft.Web/sites')
    # check availability returns true to name_available  == site does not exist
    return site_availability.name_available


def get_app_details(cmd, name):
    client = web_client_factory(cmd.cli_ctx)
    data = (list(filter(lambda x: name.lower() in x.name.lower(), client.web_apps.list())))
    if len(data) > 0:
        return data[0]
    return None


def get_rg_to_use(user, loc, os, rg_name=None):
    if rg_name is None:
        logger.info('Using default ResourceGroup value')
        return "{}_rg_{}_{}".format(user, os, loc.replace(" ", "").lower())
    else:
        return rg_name


def get_profile_username():
    from azure.cli.core._profile import Profile
    user = Profile().get_current_account_user()
    user = user.split('@', 1)[0]
    if len(user.split('#', 1)) > 1:  # on cloudShell user is in format live.com#user@domain.com
        user = user.split('#', 1)[1]
    return user


def get_sku_to_use(src_dir, sku=None):
    if sku is None:
        lang_details = get_lang_from_content(src_dir)
        return lang_details.get("default_sku")
    else:
        logger.info("Found sku argument, skipping use default sku")
        return sku


def set_language(src_dir):
    lang_details = get_lang_from_content(src_dir)
    return lang_details.get('language')


def detect_os_form_srcDir(src_dir):
    lang_details = get_lang_from_content(src_dir)
    language = lang_details.get('language')
    return "Linux" if language is not None and language.lower() == NODE_RUNTIME_NAME \
                        or language.lower() == PYTHON_RUNTIME_NAME else OS_DEFAULT


def get_plan_to_use(cmd, user, os, loc, sku, resource_group_name, should_create_rg, plan=None):
    client = web_client_factory(cmd.cli_ctx)
    _is_linux = True if os.lower() == 'linux' else False
    _default_asp = "{}_asp_{}_{}_0".format(user, os, loc)
    _create_new_asp = True
    if not should_create_rg and plan is None:
        print("Plan is none")
        # scenario where we get RG from user but no plan
        data = (list(filter(lambda x: sku.lower() in x.sku.name.lower() and _is_linux == x.reserved,
                            client.app_service_plans.list_by_resource_group(resource_group_name))))

        data_sorted = (sorted(data, key=lambda x: x.name))
        if len(data_sorted) > 0:
            plan_to_use = data_sorted[0].name
            _create_new_asp = False
        else:
            plan_to_use = _determine_if_default_plan_to_use(_default_asp, resource_group_name)
            _create_new_asp = False
    elif not should_create_rg and plan:
        # check the plan can be used with the rest of the configuration like SKU & OS
        data = (list(filter(lambda x: sku.lower() in x.sku.name.lower() and loc.lower() == x.location.lower() and
                            _is_linux == x.reserved and plan.lower() == x.name.lower(),
                            client.app_service_plans.list_by_resource_group(resource_group_name))))
        data_sorted = (sorted(data, key=lambda x: x.name))
        plan_to_use = data_sorted[0].name if len(data_sorted) > 0 \
            else _determine_if_default_plan_to_use(cmd, _default_asp, resource_group_name, loc, sku)
        _create_new_asp = False
    else:
        plan_to_use = _default_asp
    return {'plan': plan_to_use, 'exists': not _create_new_asp}


# az webapp up uses a default ASP as {}_asp_{}_{}_num
# this logic check if the default already exists & can be used with current configuration of SKU & OS
# else we use the
def _determine_if_default_plan_to_use(cmd, plan_name, resource_group_name, loc, sku):
    client = web_client_factory(cmd.cli_ctx)
    # check to see if ASP exists in RG & can be used or needs a new one to be created
    data = client.app_service_plans.get(resource_group_name, plan_name)
    if data is not None and data.sku.name.lower() == sku.lower() and data.location.lower() == loc.lower():  # the ASP exists, need to check if this can be used with the current configuration
        asp_item = data.name
    else:  # this means that plan with the name exists but cannot be used with the configuration of SKU, loc
        # we get all ASP that might exist with the name format "{}_asp_{}_{}_num"
        # get the one with the highest & add 1 to the num
        _asp_generic = plan_name[:-len(plan_name.split("_")[4])]  # returns the name as user_asp_os_loc
        d = list(filter(lambda x: _asp_generic in x.name, client.app_service_plans.list_by_resource_group(resource_group_name)))
        data_sorted = (sorted(d, key=lambda x: x.name))
        selected_asp = data_sorted[0]
        print('selected_asp is')
        print(selected_asp)
        asp_item = selected_asp.name
        print(asp_item)
        # _asp_num = int(_plan_info.name.split('_')[4]) + 1
        #asp = "{}_asp_{}_{}_{}".format(user, os, loc, _asp_num)
    return asp_item









