# Live trips and safety: upgrade guide

## What was added
| Area | What it does |
|---|---|
| Nearest-driver matching | Trips are offered to the closest online driver (within `DISPATCH_MAX_RADIUS_KM`), then the next closest if declined or ignored. Needs a recent GPS position from the driver. |
| Live driver location | The driver's browser reports GPS every 5 s on a trip (15 s when only online). Passengers see a moving car on a map with an ETA. Route history is saved during a trip. |
| Instant updates | Server-sent events push "something changed" hints and positions. Pages poll slowly (3x) as a safety net and instantly when told to. |
| Phone notifications | Optional Web Push (needs VAPID keys). |
| Pickup ETA and distance | Shown to the driver on offers and live on both sides; stored on the ride. |
| No-driver handling | Offers already moved to the next driver; now a ride with no driver after `RIDE_SEARCH_TIMEOUT_MINUTES` (10) is cancelled, vouchers released, passenger told. |
| Trip PIN | The passenger gets a 4-digit PIN; the driver cannot start the trip without it (5 wrong tries lock it for 5 min). |
| Share my trip | Passenger creates a read-only tracking link (first names only). Stops when revoked, expired or the trip ends. |
| SOS | Alerts admins (in-app and push), saves an incident with location, texts emergency contacts a tracking link. Admin review at `/admin/safety`. |
| Emergency contacts | `/trip-safety/contacts` (up to 5 per person). |
| Driver document gate | Optional: set `DISPATCH_REQUIRED_DOC_TYPES=DRIVING_PERMIT,NATIONAL_ID` so only drivers with APPROVED, unexpired documents get trips. |

## Deploy steps
1. Copy the files over the repo and push to GitHub. The first start after this deploy runs the database upgrade once (new tables and columns are added automatically).
2. In Render, make sure the start command has `--threads 32` (each open live stream holds one thread; `REALTIME_MAX_STREAMS` defaults to 20).
3. Optional, for phone notifications: run `cd rideeasy && python scripts/generate_vapid_keys.py` and set `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` in Render.
4. Optional, for SOS texts: set `EGOSMS_API_URL` and `EGOSMS_API_KEY` (already used for payments).
5. Optional, for map tiles on the live map: `LOCATIONIQ_API_KEY` (otherwise OpenStreetMap tiles are used).

## Settings (environment variables)
| Variable | Default | Meaning |
|---|---|---|
| `DISPATCH_REQUIRE_DRIVER_LOCATION` | `1` | Drivers without a recent location get no trips. `0` ranks them last instead. |
| `DISPATCH_MAX_RADIUS_KM` | `15` | Largest pickup distance for an offer. |
| `DISPATCH_LOCATION_MAX_AGE_SECONDS` | `180` | How fresh a driver position must be. |
| `RIDE_SEARCH_TIMEOUT_MINUTES` | `10` | Auto-cancel unmatched rides (`0` turns it off). |
| `ETA_AVERAGE_SPEED_KMH` | `25` | Used for ETAs (straight-line distance x 1.3 / speed). |
| `REQUIRE_TRIP_PIN` | `1` | Driver must enter the PIN to start. |
| `TRIP_SHARE_HOURS` | `12` | How long a share link can live. |
| `EMERGENCY_NUMBER` | `999` | Shown on SOS and the share page. |
| `REALTIME_MAX_STREAMS` | `20` | Maximum open live streams on this server. |

## Limits you should know about
* **Background GPS.** A website cannot track a driver whose screen is locked or who switched apps. Drivers must keep RideEasy open (the app asks the phone to keep the screen on during a trip). For reliable tracking build a native driver app.
* **One server only.** Live events are held in memory, so they work with a single Render instance and one gunicorn worker. Several instances need a shared broker such as Redis.
* **Identity checks.** The trip PIN and optional document gate are built in. Real ID or face verification needs a verification provider and is not included.
* **ETAs** are estimates from distance and average speed, not live traffic. A routing service could replace this later.
* **iPhone notifications** only work when RideEasy is added to the Home Screen.

## Tests
* `python -m pytest` (188 tests including live tracking, safety, push delivery and a full trip).
* `node tests/js/poller_test.cjs` (browser polling logic).
