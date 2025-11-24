# REST API

Home Assistant provides a RESTful API on the same port as the web frontend (default port is port 8123).

- `http://IP_ADDRESS:8123/` is an interface to control Home Assistant.
- `http://IP_ADDRESS:8123/api/` is a RESTful API.

The API accepts and returns only JSON encoded objects.
All API calls have to be accompanied by the header `Authorization: Bearer TOKEN`, where TOKEN is replaced by your unique access token. You obtain a token ("Long-Lived Access Token") by logging into the frontend using a web browser, and going to your profile.

## Actions

The API supports the following actions:

### `/api/`
Returns a message if the API is up and running.
```json
{ "message": "API running."}
```

### `/api/config`
Returns the current configuration as JSON.

### `/api/components`
Returns a list of currently loaded components.

### `/api/events`
Returns an array of event objects. Each event object contains event name and listener count.

### `/api/services`
Returns an array of service objects. Each object contains the domain and which services it contains.

### `/api/history/period/<timestamp>`
Returns an array of state changes in the past. Each object contains further details for the entities.
The `<timestamp>` (YYYY-MM-DDThh:mm:ssTZD) is optional and defaults to 1 day before the time of the request.

Parameters:
- `filter_entity_id=<entity_ids>` (required): comma separated list of entity IDs.
- `end_time=<timestamp>`: end of the period.
- `minimal_response`: only return last_changed and state.
- `no_attributes`: skip attributes.
- `significant_changes_only`: only return significant changes.

### `/api/logbook/<timestamp>`
Returns an array of logbook entries.
Parameters:
- `entity=<entity_id>`
- `end_time=<timestamp>`

### `/api/states`
Returns an array of state objects.

### `/api/states/<entity_id>`
Returns a state object for specified entity_id. Returns 404 if not found.

**POST** to this endpoint updates or creates a state.
```json
{ "state": "below_horizon", "attributes": { "next_rising":"2016-05-31T03:39:14+00:00" }}
```

**DELETE** to this endpoint deletes an entity.

### `/api/error_log`
Retrieve all errors logged during the current session as plaintext.

### `/api/camera_proxy/<camera entity_id>`
Returns the data (image) from the specified camera entity_id.

### `/api/calendars`
Returns the list of calendar entities.

### `/api/calendars/<calendar entity_id>`
Returns the list of calendar events.
Parameters:
- `start=<timestamp>`
- `end=<timestamp>`

### `/api/events/<event_type>`
**POST** fires an event with event_type.

### `/api/services/<domain>/<service>`
**POST** calls a service within a specific domain.
Optional `?return_response` to get changed states and service response.

### `/api/template`
**POST** renders a Home Assistant template.
```json
{ "template": "Paulus is at {{ states('device_tracker.paulus') }}!"}
```

### `/api/config/core/check_config`
Trigger a check of configuration.yaml.

### `/api/intent/handle`
**POST** handles an intent.
