"""Module for parsing zap files for use in sample_app_util.py.


Note on generating the hash:
  Care must be taken to produce a hash value which is not affected by updates to the zap file.
  For this reason, it is necessary to ensure a consistent order for all lists. It is also
  necessary to generate a minimum set of parameters that can be used to uniquely identify a
  particular build. In this case, the hash is generated from the metadata file data.

  The actual hash is generated by digesting the output from json.dumps() with `sort_keys=True`.
  The json lib is a good choice here because it is a Python standard lib and the output is
  unlikely to change. Additionally, using `sort_keys=True` provides us with a guaranteed output
  for the ordering of dict keys.

  After generating the hash, the hash is converted to base64 and the first 10 characters are used.
  The probability of a collision (with 100,000 items) is 1-exp(-100000^2/62^10) ~= 1.2 x 10^-8.

Conventions used for constructing the metadata file:
  - All lists are sorted alphabetically.
  - If a list contains dicts, it will be sorted by the "name" key. If it does not contain "name"
    key, it will be sorted by the first key common to all dicts that comes first alphabetically.
  - The list of endpoints is excluded from the above conventions. Endpoints are ordered according
    to their endpoint number; here, the endpoint number is the same as the order they are read
    from the zap file.

Future work:
  - _load_matter_device_types should be updated to get the mapping for device type ID and device
    name from the matter spec directly. This should be done once the matter spec becomes publicly
    available.
  - Add support for .matter files.
"""
import copy
import json
import os
import re
import uuid
from typing import Dict, List, Optional, Sequence, TypedDict, Union

try:
    import yaml
except ImportError:
    print("Missing yaml library. Install with:\npip install pyyaml")
    exit(1)

_NETWORK_COMMISSIONING_CODE = "49"
_FEATURE_MAP_CODE = "65532"

_ATTRIBUTE_ALLOW_LIST = (
    _FEATURE_MAP_CODE,  # Feature Map
)

_HERE = os.path.abspath(os.path.dirname(__file__))
_MATTER_DEVICE_LIST = os.path.join(_HERE, "matter_device_types.json")


class ClusterType(TypedDict):
    commands: List[str]
    attributes: Dict[str, str]


class EndpointType(TypedDict):
    client_clusters: Dict[str, ClusterType]
    server_clusters: Dict[str, ClusterType]


def _convert_metadata_name(name: str, code: Union[int, str]) -> str:
    """Converts a name for use in a metadata file - CamelCaseName/ID."""
    # Preserve camel case if it's already there
    name = re.sub(r"([A-Z]+)", r" \1", name).title()
    # Convert to camel case and append ID
    return re.sub(r"[^a-zA-Z]+", "", name.title()) + f"/{int(code)}"


def _convert_filename(name: str) -> str:
    """Converts a pretty name into a file friendly one."""
    return re.sub(r"[^a-zA-Z]+", "", name).lower()


def _load_matter_device_types() -> Dict[Union[int, str], Union[int, str]]:
    """Load matter device type reversible mapping.

    This function should be updated to pull from the Matter spec once it is available publicly.

    Returns:
      A dictionary mapping Matter device type IDs to their proper name and vice versa.
    """
    with open(_MATTER_DEVICE_LIST) as f:
        mapping = json.loads(f.read())
        reverse_mapping = {}
        for key, val in mapping.items():
            reverse_mapping[val] = key
        mapping.update(reverse_mapping)
    return mapping


def _read_value(input_string: str) -> str:
    """Convert various numeric forms to regular decimal format if possible."""
    ret_val = ""
    if not input_string:
        ret_val = ""
    elif "0x" in input_string:
        ret_val = int(input_string, 16)
    elif "." in input_string:
        try:
            ret_val = float(input_string)
        except ValueError:
            pass
    else:
        try:
            ret_val = int(input_string)
        except ValueError:
            pass
    return str(ret_val)


def _convert_metadata_to_hashable_digest(metadata_input: Sequence[Dict[str, EndpointType]]) -> str:
    """Converts metadata input into a hashable digest.

    Note that the output produced here is consistent across runs. Lists are sorted and dictionaries
    are sorted by their keys.

    Args:
      metadata_input: Metadata input produced from a zap file or read in from the hashable file.

    Returns:
      Hashable string for digest into a hash algorithm.
    """
    metadata = copy.deepcopy(metadata_input)

    # Replace endpoint, cluster, attribute, and commands names with IDs

    # Replace endpoint names
    for endpoint in metadata:
        endpoint_key = list(endpoint.keys())[0]
        endpoint_id = _get_id(endpoint_key)
        endpoint[endpoint_id] = endpoint.pop(endpoint_key)
        endpoint_obj = endpoint[endpoint_id]

        # Replace cluster names
        for cluster_type in ["client_clusters", "server_clusters"]:
            for cluster_key in list(endpoint_obj[cluster_type].keys()):
                cluster_id = _get_id(cluster_key)
                endpoint_obj[cluster_type][cluster_id] = endpoint_obj[cluster_type].pop(
                    cluster_key)
                cluster_obj = endpoint_obj[cluster_type][cluster_id]

                # Replace attribute names
                attribute_obj = cluster_obj.get("attributes", [])
                attribute_keys = list(attribute_obj)
                for attribute_key in attribute_keys:
                    attribute_id = _get_id(attribute_key)
                    attribute_obj[attribute_id] = attribute_obj.pop(
                        attribute_key)

                # Replace command names
                if "commands" in cluster_obj:
                    command_keys = cluster_obj["commands"]
                    cluster_obj["commands"] = [
                        _get_id(x) for x in command_keys]
                    cluster_obj["commands"].sort()

    return json.dumps(metadata, sort_keys=True)


def _get_id(name):
    """Gets id from a condensed name which is formatted like: name/id."""
    return name.split("/")[-1]


def generate_hash() -> str:
    """Generates a hash for a zap file.

    Returns:
      A 10 character alphanumeric hash.
    """
    return str(uuid.uuid4())[-10:]


def generate_metadata(
        zap_file_path: str,
        attribute_allow_list: Optional[Sequence[str]] = _ATTRIBUTE_ALLOW_LIST,
        include_commands: bool = False,
        include_platform_specific_info: bool = False) -> List[Dict[str, EndpointType]]:
    """Parses a zap_file and returns structure containing minimal content.

    The lists provided in the returned objects are sorted except for the top level list of endpoints.
    Lists containing dicts will be sorted by the "name" key of the individual dicts.

    Args:
      zap_file_path: Path to the zap file.
      attribute_allow_list: List of attribute IDs which are included in the metadata.
        If set to None then all attributes will be included.
      include_commands: Whether to include commands in the metadata.
      include_platform_specific_info: Whether to include platform specific information.
        Omitting this allows us to generate a hash that is agnostic of the platform.

    Returns:
      Dictionary containing information about endpoints and clusters. Format will be as follows:
      [
        {
          <endpoint_0_name>/<endpoint_0_id>: {
            "server_clusters": {
              <cluster_name>/<cluster_id>: {
                  "commands": [
                    <command_name>/<command_id>
                  ],
                  "attributes": {
                      <attribute_name>/<attribute_id>: <attribute_value>,
                  }
              }
            }
            "client_clusters": { ... }
          }
          <endpoint_1_name>/<endpoint_1_id>: { ... }
        }
      ]
    """
    endpoint_names = _load_matter_device_types()
    with open(zap_file_path) as f:
        app_data = json.loads(f.read())

    return_obj: List[Dict[str, EndpointType]] = []

    for endpoint in app_data["endpointTypes"]:
        device_type_id = endpoint["deviceTypeCode"]
        device_type_name = endpoint_names[device_type_id]

        endpoint_ref = _convert_metadata_name(device_type_name, device_type_id)
        endpoint_obj: Dict[str, EndpointType] = {endpoint_ref: {}}
        return_obj.append(endpoint_obj)

        client_clusters: Dict[str, ClusterType] = {}
        server_clusters: Dict[str, ClusterType] = {}

        endpoint_obj[endpoint_ref]["client_clusters"] = client_clusters
        endpoint_obj[endpoint_ref]["server_clusters"] = server_clusters

        for cluster in endpoint["clusters"]:
            # The network commissioning cluster contains platform specific details
            # such as how the platform will be commissioned to the matter fabric.
            if (not include_platform_specific_info and
                    str(cluster["code"]) == _NETWORK_COMMISSIONING_CODE):
                continue
            if not cluster["enabled"]:
                continue

            cluster_ref = _convert_metadata_name(
                cluster["name"], cluster["code"])

            if include_commands:
                cluster_obj: ClusterType = {"attributes": {}, "commands": []}
            else:
                cluster_obj: ClusterType = {"attributes": {}}

            attributes = cluster.get("attributes", [])
            for attribute in attributes:
                attribute_allowed = (
                    attribute_allow_list is None or str(attribute["code"]) in attribute_allow_list)
                if attribute["included"] and attribute_allowed:
                    attribute_ref = _convert_metadata_name(
                        attribute["name"], attribute["code"])
                    value = _read_value(attribute["defaultValue"])
                    cluster_obj["attributes"][attribute_ref] = value

            # Add a default feature map if none is provided
            if "FeatureMap/65532" not in cluster_obj["attributes"]:
                cluster_obj["attributes"]["FeatureMap/65532"] = "0"

            if include_commands:
                for command in cluster["commands"]:
                    command_ref = _convert_metadata_name(
                        command["name"], command["code"])
                    if cluster["side"] == "client" and command["outgoing"] == 1:
                        cluster_obj["commands"].append(command_ref)
                    elif cluster["side"] == "server" and command["incoming"] == 1:
                        cluster_obj["commands"].append(command_ref)

                cluster_obj["commands"] = sorted(cluster_obj["commands"])

            if cluster["side"] == "client":
                client_clusters[cluster_ref] = cluster_obj
            else:
                server_clusters[cluster_ref] = cluster_obj

    return return_obj


def generate_metadata_file(zap_file_path: str) -> str:
    """Generates metadata file for a zap file.

    The purpose of this file is to inform the user what data was included in the hash digest.

    Args:
      zap_file_path: Path to the zap file to parse for generating the metadata file.
    """
    parsed = generate_metadata(zap_file_path)
    output = yaml.dump(parsed, indent=4, sort_keys=True)

    dirname, filename = os.path.split(zap_file_path)

    filename = os.path.splitext(filename)[0]
    output_file_path = os.path.join(dirname, f"{filename}_meta.yaml")
    with open(output_file_path, "w") as f:
        f.write(output)
    return output_file_path


def generate_name(zap_file_path: str) -> str:
    """Generates the name for a zap file following convention.

    Args:
      zap_file_path: Path to the zap file to parse for generating the metadata file.

    Returns:
      Name of the file generated by following the convention.
    """
    parsed = generate_metadata(zap_file_path)
    names = []
    for endpoint in parsed:
        name = next(iter(endpoint))
        names.append(_convert_filename(name))
    hash_string = generate_hash()
    return "_".join(names) + f"_{hash_string}"
