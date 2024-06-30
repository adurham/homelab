import requests

def fetch_and_delete_alerts(url, session):
    total_deleted = 0
    params = {
        "limit": 250
    }
    more_alerts = True

    while more_alerts:
        headers = {
            "session": session
        }
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            alerts = data["data"]
            if not alerts:
                more_alerts = False
                print("No more alerts.")
            else:
                ids = [alert["id"] for alert in alerts]
                delete_url = f"{url}"
                delete_params = {
                    "id": ids
                }
                delete_response = requests.delete(delete_url, headers=headers, params=delete_params)
                if delete_response.status_code == 204:
                    total_deleted += len(ids)
                    print(f"Successfully deleted {len(ids)} alerts. Total deleted: {total_deleted}")
                else:
                    print(f"Failed to delete alerts. Status code:", delete_response.status_code)
                    break
                if len(alerts) < 250:
                    more_alerts = False
                    print("No more alerts.")
                else:
                    params["offset"] = len(alerts) + params.get("offset", 0)
        else:
            print("Failed to fetch data. Status code:", response.status_code)
            break

url = "https:///plugin/products/threat-response/api/v1/alerts"
session = ""

fetch_and_delete_alerts(url, session)
