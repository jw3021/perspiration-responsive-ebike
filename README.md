# Beyond E-Assistance: Perspiration-Responsive Motor Control for Urban E-Bikes

**MEng Design Engineering — Imperial College London**
Josh Williams · Supervisor: Robert Shorten · 2025–2026

---

## Overview

This repository contains the full software stack for a proof-of-concept e-bike system that predicts when a rider is approaching sweat onset and responds by increasing motor assistance — before visible perspiration occurs.

Sweating is the most commonly cited non-distance barrier to commuter cycling. Current pedal-assist systems respond only to mechanical inputs (torque, cadence) and have no awareness of the rider's thermal state. This project closes that gap by:

1. Instrumenting an e-bike to capture rider effort, environmental conditions, and real-time sweat data
2. Training a personalised Random Forest classifier to predict sweat onset from bike-derived features alone
3. Deploying the model onboard a Raspberry Pi to drive a two-part actuation strategy: a sustained assist ceiling increase and a targeted low-speed boost for standing starts

The trained model achieved **88.4% accuracy** and an **AUC of 0.924**, with a mean prediction lead time of **6.9 minutes**. During a live actuation ride, average rider leg power fell from 276 W to 207 W — a **24.9% reduction**.

---

## Repository Structure

```
├── ebike_controller.py       # Main onboard controller — motor control, logging, ML inference
├── config.py                 # All hardware pin assignments, control parameters, and ML config
├── web_server.py             # Rider-facing web dashboard (mode selection, live status)
├── sweat_sensor_reader.py    # hDrop wearable interface via Android Debug Bridge (ADB)
├── email_notifier.py         # Background email alerts for system events
├── plot_style.py             # Shared matplotlib theme used across all analysis scripts
├── ebike.service             # systemd unit file for autostart on the Raspberry Pi
├── requirements.txt          # Python dependencies
│
├── Data_analysis/
│   ├── 00_assist_characterisation.py   # Motor voltage-to-torque mapping validation
│   ├── analyse_last_ride.py            # Full dashboard for any data-collection ride
│   ├── analyse_actuation_ride.py       # Dashboard focused on ML trigger vs sweat onset
│   ├── dataset_coverage.py             # Ride dataset summary and coverage statistics
│   ├── dataset_spread_plots.py         # Distribution plots across the full dataset
│   ├── database_stats.py               # Supabase database row counts and health checks
│   └── backfill_ride_survey.py         # Manually add a post-ride comfort rating if missed
│
├── machine_learning/
│   ├── run_ml_pipeline.py              # Runs the full training pipeline end-to-end
│   ├── sweat_onset_model/
│   │   ├── 02_feature_engineering.py   # Pulls ride data from Supabase, builds training dataset
│   │   ├── 04_train_sweat_onset_model.py  # Trains and evaluates the Random Forest classifier
│   │   ├── 06_threshold_sweep.py       # Sweeps classification threshold to tune precision/recall
│   │   ├── sweat_onset_model.pkl       # Trained model (joblib)
│   │   ├── training_dataset.csv        # Feature-engineered dataset used for training
│   │   ├── model_config.json           # Feature list, threshold, and training metadata
│   │   └── graphics/                   # Training output plots (ROC, confusion matrix, etc.)
│   └── correlation_plots/
│       ├── 03_eda_ride_survey.py              # EDA: survey ratings vs ride conditions
│       ├── 03.5_peak_sweat_rate_survey.py     # Peak sweat rate distributions across rides
│       └── 03.6_mean_active_sweat_rate_survey.py
│
├── hardware_tests/
│   ├── test_peripherals.py             # Full I2C, GPIO, and serial hardware check
│   ├── test_dac.py                     # MCP4725 DAC output verification
│   ├── test_sensors.py                 # Torque and cadence sensor validation
│   └── test_cycle_analyst_raw.py       # Cycle Analyst serial stream monitor
│
└── docs/
    ├── SETUP_GUIDE.md                  # Hardware wiring and first-time software setup
    ├── DEVELOPMENT_GUIDE.md            # Development workflow and SSH configuration
    ├── WIRELESS_SETUP.md               # Pi hotspot and wireless connection setup
    └── Beyond-e-assistance_Risk_Assessment.xlsx
```

---

## Hardware

| Component | Role |
|---|---|
| Raspberry Pi Zero 2W | Central controller — runs all Python processes onboard |
| THUN X-CELL RT | Bottom-bracket torque and cadence sensor |
| ADS1115 ADC | Reads torque sensor analogue voltage over I2C |
| MCP4725 DAC | Outputs 0–4.5 V motor command voltage over I2C |
| AHT25 | Ambient temperature and relative humidity |
| Grinfineon C4820-GR | Motor controller — accepts 0–5 V analogue assist command |
| Cycle Analyst V3 | Speed, battery voltage, current, and motor power over serial |
| hDrop wearable | Upper-arm capacitive sweat sensor (calibration rides only) |
| Android phone | Runs the hDrop app; connected to Pi via USB for ADB data extraction |
| DC-DC buck converter | Steps 36 V e-bike battery down to 5 V for Pi and peripherals |

Full wiring details are in [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md).

---

## Setup

### 1. Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configuration

Edit `config.py` to set your Supabase credentials, hardware pin assignments, and ML model path. All tuneable parameters — assist voltage bands, onset thresholds, ramp rates — are documented in that file.

### 3. Hardware checks

Before a ride, verify all peripherals from the `hardware_tests/` directory on the Pi:

```bash
python hardware_tests/test_peripherals.py   # full I2C + GPIO + serial check
python hardware_tests/test_dac.py           # confirm DAC output voltage
```

### 4. Autostart (optional)

To run the controller automatically on boot:

```bash
sudo cp ebike.service /etc/systemd/system/
sudo systemctl enable ebike
sudo systemctl start ebike
```

---

## Usage

### Running the controller

```bash
python ebike_controller.py
```

The rider selects **data-collection mode** (sweat sensor active, normal assist) or **actuation mode** (ML model active, sweat-reduction assist) from the web dashboard, accessible from a phone browser on the same network.

### Training the ML model

From the `machine_learning/` directory:

```bash
python run_ml_pipeline.py
```

This runs the three pipeline stages in sequence:
1. `02_feature_engineering.py` — pulls ride data from Supabase, computes rolling features, writes `training_dataset.csv`
2. `04_train_sweat_onset_model.py` — trains the Random Forest, evaluates on held-out rides, writes `sweat_onset_model.pkl` and `model_config.json`
3. `06_threshold_sweep.py` — sweeps the classification threshold and plots precision/recall trade-offs

### Analysing rides

```bash
# Latest data-collection ride
python Data_analysis/analyse_last_ride.py

# Latest actuation ride (ML trigger vs sweat onset)
python Data_analysis/analyse_actuation_ride.py

# Specific ride by ID
python Data_analysis/analyse_actuation_ride.py RIDE_20260528_090603
```

---

## Results

| Metric | Value |
|---|---|
| Test accuracy | 88.4% |
| AUC | 0.924 |
| Mean prediction lead time | 6.9 minutes |
| Rider leg power reduction (actuation ride) | 24.9% (276 W → 207 W) |

Model trained on a single rider across multiple commuting-length rides. All evaluation is on rides held out from training (ride-grouped split).

---

## Acknowledgements

Supervisor: Robert Shorten, Dyson School of Design Engineering, Imperial College London.

The e-bike platform was inherited from Shaun Sweeney's 2017 MEng thesis, which provided the bike frame, hub motor, battery, and Cycle Analyst.

This codebase was developed with the assistance of Claude (Anthropic) as an AI coding assistant.
