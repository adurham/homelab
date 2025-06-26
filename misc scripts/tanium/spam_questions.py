import time
import requests
import random
import urllib3
from urllib3.exceptions import NotOpenSSLWarning
import warnings

# Suppress SSL and LibreSSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

BASE_URL = "https://172.16.1.18"
SENSORS_URL = f"{BASE_URL}/api/v2/sensors"
PARSE_URL = f"{BASE_URL}/api/v2/parse_question"
QUESTION_URL = f"{BASE_URL}/api/v2/questions"

HEADERS = {
    "Content-Type": "application/json",
    "Session": "token-"  # Replace with your session header and token
}

EXPIRE_SECONDS = 600
MAX_AGE_SECONDS = 60
TOTAL_REQUESTS = 1800  # 10 minutes

failed_requests = []
success_count = 0


def fetch_sensor_names():
    try:
        resp = requests.get(SENSORS_URL, headers=HEADERS, verify=False)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            names = [
                item.get("name") for item in data
                if "name" in item and not item.get("exclude_from_parse_flag", False) and not item.get("hidden_flag", False)
            ]
            return names
    except Exception:
        pass
    return []


def generate_question_text(sensor_names):
    selected = random.sample(sensor_names, min(30, len(sensor_names)))
    quoted = [f'"{name.strip()}"?maxAge={MAX_AGE_SECONDS}' for name in selected]
    return f'Get?expireSeconds={EXPIRE_SECONDS} {" and ".join(quoted)} from all machines'


def parse_question(raw_query):
    try:
        resp = requests.post(PARSE_URL, json={"text": raw_query}, headers=HEADERS, verify=False)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data and "question_text" in data[0]:
                return data[0]["question_text"]
    except Exception:
        pass
    return None


def send_question(query_text, max_retries=3):
    global success_count
    payload = {
        "query_text": query_text
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(QUESTION_URL, json=payload, headers=HEADERS, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                question_id = data.get("data", {}).get("id")
                if question_id is not None:
                    print(f"Question ID: {question_id}")
                    success_count += 1
                    return
                else:
                    reason = "Missing ID in successful response"
            else:
                reason = f"HTTP {resp.status_code} - {resp.text}"
        except Exception as e:
            reason = f"Exception: {str(e)}"

        print(f"Attempt {attempt} failed: {reason}")
        if attempt < max_retries:
            time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s, 8s
        else:
            failed_requests.append(f"{reason}")


if __name__ == "__main__":
    sensor_name_pool = fetch_sensor_names()
    if not sensor_name_pool:
        print("Aborting: could not fetch sensor names.")
        exit(1)

    try:
        for _ in range(TOTAL_REQUESTS):
            raw_question = generate_question_text(sensor_name_pool)
            # parsed_question = parse_question(raw_question)  # Disabled for now
            send_question(raw_question)
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    print("\n--- Summary of Failed Requests ---")
    print(f"Total failures: {len(failed_requests)}")
    print(f"Total successful: {success_count}")
