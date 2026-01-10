import json
from src.requests import (
    cloudflare_gateway_request, retry, rate_limited_request, retry_config
)


@retry(**retry_config)
@rate_limited_request
def create_list(name, domains):
    endpoint = "/lists"
    data = {
        "name": name,
        "description": "Ads & Tracking Domains",
        "type": "DOMAIN",
        "items": [{"value": domain} for domain in domains]
    }
    status, response = cloudflare_gateway_request("POST", endpoint, body=json.dumps(data))
    return response["result"]

@rate_limited_request
def update_list(list_id, remove_items, append_items):
    from src.requests import HTTPException
    endpoint = f"/lists/{list_id}"
    remove_list = list(remove_items)

    # Try updating the list; if we get a 400 "not found" error, filter and retry
    max_retries = 3
    for attempt in range(max_retries):
        data = {
            "remove": remove_list,
            "append": [{"value": domain} for domain in append_items]
        }
        try:
            status, response = cloudflare_gateway_request("PATCH", endpoint, body=json.dumps(data))
            return response["result"]
        except HTTPException as e:
            # Check if this is a "not found in list" error (items already removed)
            if "not found in list" in str(e) and attempt < max_retries - 1:
                # Extract the domain that wasn't found from the error message
                import re
                match = re.search(r'"message":\s*"(item to be removed, )?([^,]+)(, not found in list)?"', str(e))
                if match:
                    not_found_domain = match.group(2)
                    from src import silent_error
                    silent_error(f"Domain '{not_found_domain}' not in list (already removed), filtering and retrying")
                    # Remove the problematic domain from remove_list
                    if not_found_domain in remove_list:
                        remove_list.remove(not_found_domain)
                    # Retry with filtered list
                    continue
            # If it's not a "not found" error or we've exhausted retries, raise
            raise

    return None  # Should never reach here

@retry(**retry_config)
def create_rule(rule_name, list_ids):
    endpoint = "/rules"
    data = {
        "name": rule_name,
        "description": "Block Ads & Tracking",
        "action": "block",
        "traffic": " or ".join(f'any(dns.domains[*] in ${lst})' for lst in list_ids),
        "enabled": True,
    }
    status, response = cloudflare_gateway_request("POST", endpoint, body=json.dumps(data))
    return response["result"]

@retry(**retry_config)
def update_rule(rule_name, rule_id, list_ids):
    endpoint = f"/rules/{rule_id}"
    data = {
        "name": rule_name,
        "description": "Block Ads & Tracking",
        "action": "block",
        "traffic": " or ".join(f'any(dns.domains[*] in ${lst})' for lst in list_ids),
        "enabled": True,
    }
    status, response = cloudflare_gateway_request("PUT", endpoint, body=json.dumps(data))
    return response["result"]

@retry(**retry_config)
def get_lists(prefix_name):
    status, response = cloudflare_gateway_request("GET", "/lists")
    lists = response["result"] or []
    return [l for l in lists if l["name"].startswith(prefix_name)]

@retry(**retry_config)
def get_rules(rule_name_prefix):
    status, response = cloudflare_gateway_request("GET", "/rules")
    rules = response["result"] or []
    return [r for r in rules if r["name"].startswith(rule_name_prefix)]

@retry(**retry_config)
@rate_limited_request
def delete_list(list_id):
    endpoint = f"/lists/{list_id}"
    status, response = cloudflare_gateway_request("DELETE", endpoint)
    return response["result"]

@retry(**retry_config)
def delete_rule(rule_id):
    endpoint = f"/rules/{rule_id}"
    status, response = cloudflare_gateway_request("DELETE", endpoint)
    return response["result"]

@retry(**retry_config)
def get_list_items(list_id):
    endpoint = f"/lists/{list_id}/items?limit=1000"
    status, response = cloudflare_gateway_request("GET", endpoint)
    items = response["result"] or []
    return [i["value"] for i in items]
