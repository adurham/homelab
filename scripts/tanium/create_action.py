import http.client
import json
import time
from urllib.parse import quote

API_HOST = ""  # e.g., "api.example.com"
API_TOKEN = "token-"
QUESTION_TEXT = "Get Online from all machines with Is Windows equals True"
ACTION_GROUP_NAME = "Default"
PACKAGE_NAME = "Endpoint Configuration - Reset Components [Windows]"


HEADERS = {
    "Content-Type": "application/json",
    "session": f"{API_TOKEN}"
}


def https_post(path, body):
    conn = http.client.HTTPSConnection(API_HOST)
    conn.request("POST", path, body=json.dumps(body), headers=HEADERS)
    resp = conn.getresponse()
    if resp.status != 200:
        raise Exception(f"POST {path} failed with status {resp.status}: {resp.read().decode()}")
    data = resp.read()
    conn.close()
    return json.loads(data)


def https_get(path):
    conn = http.client.HTTPSConnection(API_HOST)
    conn.request("GET", path, headers=HEADERS)
    resp = conn.getresponse()
    if resp.status != 200:
        raise Exception(f"GET {path} failed with status {resp.status}: {resp.read().decode()}")
    data = resp.read()
    conn.close()
    return json.loads(data)


def post_question():
    body = {
        "query_text": f"{QUESTION_TEXT}"
    }
    response = https_post("/api/v2/questions", body)
    question_id = response["data"]["id"]
    print(f"Posted question. Question ID: {question_id}")
    return question_id


def poll_result_info(question_id, timeout=600, interval=30):
    path = f"/api/v2/result_info/question/{question_id}"
    start_time = time.time()

    while True:
        response = https_get(path)
        result_infos = response["data"].get("result_infos", [])
        if not result_infos:
            raise Exception("No result_infos found in response.")

        info = result_infos[0]
        estimated_total = info["estimated_total"]
        mr_tested = info["mr_tested"]

        print(f"Progress: {mr_tested}/{estimated_total} tested")

        if estimated_total > 0 and mr_tested >= estimated_total:
            print("Completion reached 100%")
            return

        if time.time() - start_time > timeout:
            print("Timeout reached. Using best-effort results.")
            return

        time.sleep(interval)


def get_result_data(question_id):
    path = f"/api/v2/result_data/question/{question_id}"

    tanium_options = {
        "aggregate_over_time_flag": None,
        "allow_cdata_base64_encode_flag": None,
        "audit_history_size": None,
        "cache_expiration": 10,
        "cache_filters": [],
        "saved_question_qids_allow_multiple_flags": None,
        "cache_id": None,
        "cache_sort_fields": None,
        "cdata_base64_encoded": None,
        "context_id": None,
        "disable_live_snapshots": None,
        "export_dont_include_related": None,
        "export_flag": None,
        "export_format": None,
        "export_hide_csv_header_flag": None,
        "export_leading_text": None,
        "export_trailing_text": None,
        "filter_not_flag": 0,
        "filter_string": None,
        "flags": None,
        "hide_errors_flag": 0,
        "hide_no_results_flag": None,
        "import_analyze_conflicts_only": None,
        "import_existing_ignore_content_set": None,
        "include_answer_times_flag": None,
        "include_hidden_flag": None,
        "include_user_details": None,
        "include_user_owned_object_ids_flag": None,
        "json_pretty_print": None,
        "live_snapshot_always_use_seconds": None,
        "live_snapshot_expiration_seconds": None,
        "live_snapshot_invalidate_report_count_percentage": None,
        "live_snapshot_report_count_threshold": None,
        "most_recent_flag": 0,
        "no_result_row_collation_flag": None,
        "pct_done_limit": None,
        "recent_result_buckets": None,
        "return_cdata_flag": None,
        "return_lists_flag": None,
        "row_count": 101,
        "row_counts_only_flag": None,
        "row_start": 0,
        "sample_count": None,
        "sample_frequency": None,
        "sample_start": None,
        "saved_question_qids_ignore_mr_group_flag": None,
        "saved_question_qids_include_expired_flag": None,
        "saved_question_qids_reissue_flag": None,
        "script_data": None,
        "sort_order": None,
        "suppress_scripts": None,
        "suppress_object_list": None,
        "use_error_objects": None,
        "use_json": None,
        "use_user_context_flag": None
    }

    headers = dict(HEADERS)
    headers["tanium-options"] = json.dumps(tanium_options)

    conn = http.client.HTTPSConnection(API_HOST)
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    if resp.status != 200:
        raise Exception(f"GET {path} failed with status {resp.status}: {resp.read().decode()}")
    data = resp.read()
    conn.close()

    response = json.loads(data)

    result_sets = response.get("data", {}).get("result_sets", [])
    if not result_sets or "cache_id" not in result_sets[0]:
        raise Exception("No result_sets or cache_id found in response.")

    cache_id = result_sets[0]["cache_id"]
    if not isinstance(cache_id, str):
        raise Exception(f"cache_id was not a string: {cache_id}")

    print(f"\nParsed cache_id: {cache_id}")
    print("\nResult Data Summary:")

    for row in result_sets[0].get("rows", []):
        data = row["data"]
        if len(data) >= 2:
            key = data[0][0]["text"]
            value = data[1][0]["text"]
            print(f"{key}: {value} machines")
        else:
            print("Unexpected row format:", row)

    return cache_id


def post_build_target_group(cache_id):
    body = {
        "cache_id": int(cache_id),
        "reference_ids": [0]
    }
    response = https_post("/api/v2/build_target_group", body)
    group_id = response["data"]["id"]
    print(f"\nTarget group created with ID: {group_id}")
    return group_id


def get_id_by_name(endpoint, name):
    safe_name = quote(name, safe="")
    path = f"/api/v2/{endpoint}/by-name/{safe_name}"
    response = https_get(path)
    return response["data"]["id"]


def post_action(target_group_id):
    action_group_id = get_id_by_name("action_groups", ACTION_GROUP_NAME)
    package_id = get_id_by_name("packages", PACKAGE_NAME)

    body = {
        "action_group": {
            "id": action_group_id
        },
        "package_spec": {
            "id": package_id,
            "parameters": [
                {
                    "key": "$1",
                    "value": "Remove All CX",
                    "type": 1
                }
            ]
        },
        "name": "Reset Components Action - Windows",
        "expire_seconds": 3600,
        "target_group": {
            "and_flag": 1,
            "id": target_group_id
        }
    }

    response = https_post("/api/v2/actions", body)
    action_id = response["data"]["id"]
    print(f"\nAction created with ID: {action_id}")
    return action_id


def main():
    try:
        question_id = post_question()
        poll_result_info(question_id)
        cache_id = get_result_data(question_id)
        target_group_id = post_build_target_group(cache_id)
        post_action(target_group_id)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
