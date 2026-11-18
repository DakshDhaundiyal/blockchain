"""
TrustHarvest — Phase 4 Research Experiment Framework
Module: generate_dataset.py

Generates reproducible, realistic synthetic produce batches across all supply chain stages
(Harvest, multi-stop Transport checkpoints, and Retail listings) for integrity benchmarking.
All generated records are strictly fictional and clearly tagged as synthetic.
"""

import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone

# Realistic synthetic produce catalogs
PRODUCE_VARIETIES = [
    ("Organic Honeycrisp Apples", "100% Certified Organic", "500 kg", "Yakima Valley, WA"),
    ("Heirloom Vine Tomatoes", "Hydroponic Greenhouse", "350 kg", "Salinas Valley, CA"),
    ("Organic Hass Avocados", "Regenerative Organic", "400 kg", "Michoacán Micro-Farm #4"),
    ("Sweet Strawberries", "Integrated Pest Management", "250 kg", "Watsonville Coastal Plains"),
    ("Baby Spinach Leaves", "Certified Organic (USDA)", "180 kg", "Yuma Agricultural Zone"),
    ("Valencia Juicing Oranges", "Conventional Sustainable", "600 kg", "Central Valley Citrus Belt"),
    ("Golden Delicious Pears", "Bio-Dynamic Certified", "300 kg", "Hood River Valley, OR"),
    ("Crisp Red Bell Peppers", "Cover Crop Soil-Grown", "220 kg", "Sonora Border Region"),
    ("Fresh Wild Blueberries", "Organic Cold-Hardy", "150 kg", "Northwest Berry Co-op"),
    ("English Seedless Cucumbers", "Clean Hydroponic", "280 kg", "Ontario Hothouse Sector B"),
]

FARM_NAMES = [
    "Green Horizon Organic Orchards",
    "Valley Crest Regenerative Farms",
    "Cascadia Bio-Dynamic Fields",
    "Sunburst Agricultural Commons",
    "Emerald Canopy Micro-Growers",
    "Highland Heritage Farmsteads",
]

CERTIFICATIONS = [
    "USDA Organic; Non-GMO Project Verified; CCOF Certified",
    "GlobalGAP Food Safety Standard; USDA Organic",
    "Regenerative Organic Certified (ROC) Bronze; Fair Trade",
    "Bio-Dynamic Demeter Standard; USDA Organic",
    "Safe Quality Food (SQF) Level 2; USDA Organic",
]

TRANSIT_HUBS = [
    ("Orchard Loading Depot", "3.2 °C", "WA-TRK-104"),
    ("Regional Pre-Cooling Center", "3.6 °C", "WA-TRK-104"),
    ("State Cold Storage Hub", "3.8 °C", "WA-TRK-208"),
    ("Highway Temperature Inspection Station", "4.0 °C", "WA-TRK-208"),
    ("Metropolitan Logistics Cross-Dock", "3.9 °C", "DIST-TRK-305"),
    ("Port Intermodal Container Yard", "3.4 °C", "DIST-TRK-401"),
    ("Central Valley Sorting Facility", "4.1 °C", "CAL-LOG-712"),
    ("Supermarket Distribution Center", "3.7 °C", "STORE-FLT-900"),
]

TRANSPORT_STATUSES = [
    "Picked Up from Farm",
    "In Transit - Regional Corridor",
    "Customs & Quality Clearance Verified",
    "Mid-Route Temperature Inspection Passed",
    "Arrived at Metropolitan Cross-Dock",
    "Out for Final Delivery to Retail",
]

RETAIL_STORES = [
    ("Whole Harvest Organic Market", "Seattle Central Branch", 4.99),
    ("Pacific Fresh Foods", "Portland Downtown Market", 3.79),
    ("Evergreen Neighborhood Grocer", "Bellevue Square Location", 5.29),
    ("Cornerstone Natural Foods", "Tacoma Harbor Store", 4.49),
    ("Urban Farmstead Market", "Vancouver Main Street", 4.89),
]


def generate_synthetic_batches(
    count: int = 30,
    seed: int = 42,
    base_batch_prefix: str = "TH-SYN",
) -> dict:
    """
    Generates a deterministic synthetic dataset of produce batches.
    Each batch includes:
    - Harvest origin details
    - 1 to 5 sequential transport checkpoints with cold-chain telemetry
    - Retail store intake and shelf-life pricing
    - Expected verification outcomes for integrity testing
    """
    rng = random.Random(seed)
    batches = []
    base_time = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)

    for i in range(1, count + 1):
        batch_id = f"{base_batch_prefix}-{i:03d}"
        produce = rng.choice(PRODUCE_VARIETIES)
        farm_name = rng.choice(FARM_NAMES)
        cert = rng.choice(CERTIFICATIONS)
        batch_offset_days = (i - 1) * 2
        harvest_dt = base_time + timedelta(days=batch_offset_days)
        packaging_date = harvest_dt.strftime("%Y-%m-%d")

        harvest_data = {
            "batch_id": batch_id,
            "name": f"Synthetic {produce[0]}",
            "quantity": produce[2],
            "farming_method": produce[1],
            "packaging_date": packaging_date,
            "farmer_id": 1,
            "image": "default.jpg",
            "farm_name": farm_name,
            "farm_location": produce[3],
            "certifications": cert,
            "notes": f"Synthetic benchmark batch #{i}. Generated strictly for research evaluation.",
        }

        # 1 to 5 sequential transport checkpoints
        num_checkpoints = rng.randint(1, 5)
        checkpoints = []
        current_time = harvest_dt + timedelta(hours=6)

        for c_idx in range(num_checkpoints):
            hub = rng.choice(TRANSIT_HUBS)
            status = TRANSPORT_STATUSES[min(c_idx, len(TRANSPORT_STATUSES) - 1)]
            # Realistic cold-chain fluctuation between 2.8°C and 4.4°C (safe range)
            temp_val = round(rng.uniform(2.8, 4.4), 1)
            temp_str = f"{temp_val} °C"

            checkpoints.append({
                "checkpoint_index": c_idx,
                "status": status,
                "current_location": hub[0],
                "temperature": temp_str,
                "vehicle_number": hub[2],
                "notes": f"Checkpoint #{c_idx + 1} telemetry confirmed within safe cold-chain band.",
                "transporter_id": 2,
                "timestamp_iso": current_time.isoformat(),
            })
            current_time += timedelta(hours=rng.randint(8, 24))

        # Retail listing
        retail_store = rng.choice(RETAIL_STORES)
        arrival_date = (current_time + timedelta(hours=4)).strftime("%Y-%m-%d")
        shelf_life_days = rng.randint(10, 21)

        retail_data = {
            "store_name": retail_store[0],
            "store_location": retail_store[1],
            "price": f"{retail_store[2]:.2f}",
            "stock_quantity": harvest_data["quantity"],
            "arrival_date": arrival_date,
            "shelf_life": f"{shelf_life_days} Days",
            "retailer_id": 3,
        }

        batches.append({
            "batch_id": batch_id,
            "is_synthetic": True,
            "synthetic_id": i,
            "created_at_iso": harvest_dt.isoformat(),
            "harvest": harvest_data,
            "transport_checkpoints": checkpoints,
            "retail": retail_data,
            "expected_baseline": {
                "harvest_outcome": "verified",
                "transport_outcome": "verified",
                "retail_outcome": "verified",
                "overall_outcome": "verified",
            },
        })

    dataset = {
        "metadata": {
            "dataset_name": "TrustHarvest Synthetic Provenance Baseline Dataset",
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_batches": len(batches),
            "seed": seed,
            "is_synthetic": True,
            "purpose": "Phase 4 baseline experiment evaluation without touching production or personal data.",
        },
        "batches": batches,
    }
    return dataset


def save_dataset(dataset: dict, filepath: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic provenance batches for Phase 4 baseline research.")
    parser.add_argument("--count", type=int, default=30, help="Number of synthetic batches to generate (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic generation (default: 42)")
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "data", "synthetic_batches.json"),
        help="Target output path for synthetic dataset JSON",
    )
    args = parser.parse_args()

    print(f"Generating {args.count} synthetic batches (seed={args.seed})...")
    dataset = generate_synthetic_batches(count=args.count, seed=args.seed)
    out_file = save_dataset(dataset, args.output)
    print(f"Synthetic dataset saved successfully to: {out_file}")
    print(f"Total batches generated: {len(dataset['batches'])}")


if __name__ == "__main__":
    main()

