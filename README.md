# T.R.A.U.T.H.

**Total Residential Automation & Utility Tracking Hub** is a Home Assistant add-on with a glowing orb interface for the house.

## Install (from the Home Assistant app)

1. **Settings → Add-ons → Add-on Store**
2. **⋮ (top right) → Repositories**, paste `https://github.com/kylejtrauth-del/trauth-home`, then tap **Add**
3. Close that window, then pull down to refresh the store. **T.R.A.U.T.H.** appears near the bottom.
4. Open it → **Install**. The first install builds on the Green and takes a few minutes.
5. Turn on **Start on boot** and **Show in sidebar** → **Start**
6. Open **TRAUTH** from the sidebar.

## Updating

When a new version is pushed here, Home Assistant shows **Update** on the add-on. Tap it. Your profiles, chores and notes are kept in the add-on's `/data` folder and included in Home Assistant backups.

## British voice (Piper)

1. **Settings → Add-ons → Add-on Store → Piper → Install**
2. In Piper's **Configuration** tab, set the voice to `en_GB-alan-medium` → **Save** → **Start**
3. **Settings → Devices & services**: accept the discovered **Wyoming Protocol** (Piper)
4. In T.R.A.U.T.H., open **Settings → Voice source → The Green · British** and pick a voice

## What it connects to

T.R.A.U.T.H. finds devices in Home Assistant automatically:

| Orb | Uses |
|---|---|
| Climate | the first `climate.*` entity (Honeywell T6 Pro via HomeKit) |
| Cameras | every `camera.*` (Ring + Blink), Blink arm/disarm, motion-detection switches |
| Security | SimpliSafe `alarm_control_panel`, door and motion sensors (any can be marked inactive) |
| Garage | the garage entry door sensor |
| TV | `media_player.*` + `remote.*` |
| Lights | any `light.*` or smart-plug `switch.*` added later |
| Calendar | any `calendar.*` (e.g. Google Calendar integration) |
| House | low batteries, open or offline doors, chores, notes |

Profiles (Kyle, Macy) are picked automatically from the Home Assistant user who is logged in.
