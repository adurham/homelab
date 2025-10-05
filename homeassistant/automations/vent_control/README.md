# Vent Control System

This directory contains the consolidated vent control automations for the Home Assistant system.

## Files

- `smart_vent_control_system.yaml` - Main automation that triggers on occupancy, temperature changes, and periodic checks
- `manual_vent_control.yaml` - Manual trigger for testing the vent control system

## How it works

1. **Occupancy Detection**: Uses Ecobee occupancy sensors to detect when rooms are occupied
2. **Temperature Monitoring**: Monitors room temperatures and compares to Ecobee setpoint
3. **Vent Control**: Controls Flair smart vents based on occupancy and temperature needs
4. **Energy Optimization**: Allows unoccupied rooms to drift ±3°F from target to save energy

## Room Configuration

The system controls vents in the following rooms:
- Kitchen (1 vent)
- Living Room (2 vents)
- Main Bedroom (3 vents)
- Guest Bedroom 2 (1 vent)
- Main Bathroom (1 vent)
- Laundry Room (1 vent)
- Hallway (1 vent)
- Dining Room (1 vent)

## Vent Positions

- **100% (Open)**: Occupied rooms for maximum comfort
- **50% (Half-open)**: Unoccupied rooms that need temperature adjustment
- **0% (Closed)**: Unoccupied rooms within temperature tolerance

## Deployment

Use the `deploy_vent_control.sh` script to deploy the system to Home Assistant.
