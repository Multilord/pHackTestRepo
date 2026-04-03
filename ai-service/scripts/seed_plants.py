"""
scripts/seed_plants.py

Seeds the MongoDB plants collection with sample data for testing.

Run from the project root:
    python scripts/seed_plants.py
"""

import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

PLANTS = [
    {
        "name": "Thai Basil",
        "botanicalName": "Ocimum basilicum var. thyrsiflora",
        "emoji": "🌿",
        "category": "Herb",
        "difficulty": "Easy",
        "spaceType": "Balcony",
        "description": "Aromatic herb with a sweet, anise-like flavour. Perfect for Southeast Asian cooking and very forgiving for beginners.",
        "idealConditions": {
            "minSunlight": 4, "maxSunlight": 8,
            "minTemp": 20, "maxTemp": 35,
            "minHumidity": 50, "maxHumidity": 85,
        },
        "careTips": {
            "sunlight": "4–6 hours of direct sunlight daily",
            "watering": "Every 2 days — keep soil moist but not waterlogged",
            "growTime": "6–8 weeks to first harvest",
            "potSize": "6-inch pot minimum",
            "fertilizer": "Monthly with balanced liquid fertilizer",
            "soilMix": "Well-draining potting mix with perlite",
            "calendar": [
                {"week": "Week 1–2", "title": "Sowing & Germination", "description": "Sow seeds 5mm deep. Keep soil warm (25–30°C). Germination in 5–10 days."},
                {"week": "Week 3–4", "title": "Seedling Stage", "description": "Thin to one plant per pot. Begin gentle watering routine."},
                {"week": "Week 5–6", "title": "Vegetative Growth", "description": "Pinch off flower buds to encourage leafy growth. Begin fertilizing."},
                {"week": "Week 7–8", "title": "First Harvest", "description": "Harvest leaves from the top down. Leave at least 2 leaf pairs per stem."},
            ],
        },
        "createdAt": datetime.now(timezone.utc),
    },
    {
        "name": "Cherry Tomato",
        "botanicalName": "Solanum lycopersicum var. cerasiforme",
        "emoji": "🍅",
        "category": "Vegetable",
        "difficulty": "Moderate",
        "spaceType": "Terrace",
        "description": "Prolific producer of sweet, bite-sized tomatoes. Thrives in full sun with good support structures.",
        "idealConditions": {
            "minSunlight": 6, "maxSunlight": 10,
            "minTemp": 18, "maxTemp": 32,
            "minHumidity": 40, "maxHumidity": 70,
        },
        "careTips": {
            "sunlight": "6–8 hours of full sun per day",
            "watering": "Daily — consistent moisture prevents blossom end rot",
            "growTime": "10–12 weeks from transplant to first harvest",
            "potSize": "12-inch pot or 10L container minimum",
            "fertilizer": "Weekly with tomato-specific fertilizer once flowering begins",
            "soilMix": "Rich potting mix with compost and slow-release fertilizer",
            "calendar": [
                {"week": "Week 1–2", "title": "Transplanting", "description": "Transplant seedlings into final pot. Water well and provide support stake."},
                {"week": "Week 3–5", "title": "Vegetative Growth", "description": "Remove suckers growing in leaf axils. Tie main stem to support."},
                {"week": "Week 6–8", "title": "Flowering", "description": "Yellow flowers appear. Gently shake plant daily to aid pollination."},
                {"week": "Week 9–12", "title": "Fruiting & Harvest", "description": "Fruits ripen from green to red. Harvest when fully coloured and slightly soft."},
            ],
        },
        "createdAt": datetime.now(timezone.utc),
    },
    {
        "name": "Mint",
        "botanicalName": "Mentha spicata",
        "emoji": "🌱",
        "category": "Herb",
        "difficulty": "Easy",
        "spaceType": "Indoor",
        "description": "Fast-growing, fragrant herb ideal for teas and cooking. Grows well indoors with indirect light.",
        "idealConditions": {
            "minSunlight": 2, "maxSunlight": 6,
            "minTemp": 15, "maxTemp": 30,
            "minHumidity": 45, "maxHumidity": 80,
        },
        "careTips": {
            "sunlight": "2–4 hours of indirect sunlight, or a bright windowsill",
            "watering": "Every 2–3 days — keep consistently moist",
            "growTime": "4–6 weeks from cutting to first harvest",
            "potSize": "8-inch pot; mint spreads aggressively",
            "fertilizer": "Every 6 weeks with balanced fertilizer",
            "soilMix": "Moisture-retaining potting mix",
            "calendar": [
                {"week": "Week 1", "title": "Planting", "description": "Plant rooted cutting or transplant seedling. Water thoroughly."},
                {"week": "Week 2–3", "title": "Establishment", "description": "New growth appears. Maintain consistent moisture."},
                {"week": "Week 4–6", "title": "First Harvest", "description": "Harvest top 1/3 of stems to encourage bushy growth."},
            ],
        },
        "createdAt": datetime.now(timezone.utc),
    },
    {
        "name": "Chili (Cili Padi)",
        "botanicalName": "Capsicum frutescens",
        "emoji": "🌶️",
        "category": "Vegetable",
        "difficulty": "Easy",
        "spaceType": "Balcony",
        "description": "The iconic small but fiery chili, a staple in Malaysian cooking. Very well adapted to tropical climates.",
        "idealConditions": {
            "minSunlight": 5, "maxSunlight": 9,
            "minTemp": 22, "maxTemp": 38,
            "minHumidity": 50, "maxHumidity": 80,
        },
        "careTips": {
            "sunlight": "5–7 hours of direct sun daily",
            "watering": "Every 2 days; allow top inch of soil to dry between watering",
            "growTime": "12–16 weeks from seed to harvest",
            "potSize": "8-inch pot",
            "fertilizer": "Bi-weekly potassium-rich fertilizer once fruiting begins",
            "soilMix": "Well-draining loamy potting mix",
            "calendar": [
                {"week": "Week 1–3", "title": "Germination & Seedling", "description": "Keep warm and moist. Transplant when 4 true leaves appear."},
                {"week": "Week 4–8", "title": "Vegetative Growth", "description": "Fertilize and ensure full sun. Pinch growing tips for bushier plant."},
                {"week": "Week 9–12", "title": "Flowering", "description": "Small white flowers appear. Ensure good air circulation."},
                {"week": "Week 13–16", "title": "Fruiting & Harvest", "description": "Harvest green for moderate heat, red for maximum heat."},
            ],
        },
        "createdAt": datetime.now(timezone.utc),
    },
    {
        "name": "Pandan",
        "botanicalName": "Pandanus amaryllifolius",
        "emoji": "🌴",
        "category": "Herb",
        "difficulty": "Easy",
        "spaceType": "Indoor",
        "description": "Fragrant tropical plant used widely in Malaysian desserts and cooking. Thrives in warm, humid indoor conditions.",
        "idealConditions": {
            "minSunlight": 2, "maxSunlight": 6,
            "minTemp": 24, "maxTemp": 36,
            "minHumidity": 60, "maxHumidity": 90,
        },
        "careTips": {
            "sunlight": "Bright indirect light; tolerates low light",
            "watering": "Every 2–3 days; loves humidity",
            "growTime": "Established plants ready to harvest in 3–4 months",
            "potSize": "10-inch pot with drainage holes",
            "fertilizer": "Monthly with balanced fertilizer",
            "soilMix": "Loamy, moisture-retaining mix",
            "calendar": [
                {"week": "Week 1–2", "title": "Planting", "description": "Plant offset or rooted cutting. Keep soil moist and humid."},
                {"week": "Week 3–8", "title": "Establishment", "description": "New leaves will emerge. Mist leaves regularly in dry conditions."},
                {"week": "Month 3–4", "title": "Harvest", "description": "Cut leaves from the outer ring. Leave the growing centre intact."},
            ],
        },
        "createdAt": datetime.now(timezone.utc),
    },
    {
        "name": "Kangkung (Water Spinach)",
        "botanicalName": "Ipomoea aquatica",
        "emoji": "🥬",
        "category": "Vegetable",
        "difficulty": "Easy",
        "spaceType": "Farm",
        "description": "Fast-growing leafy green that thrives in tropical heat. A Malaysian kitchen staple with a very quick harvest cycle.",
        "idealConditions": {
            "minSunlight": 5, "maxSunlight": 10,
            "minTemp": 25, "maxTemp": 38,
            "minHumidity": 65, "maxHumidity": 95,
        },
        "careTips": {
            "sunlight": "Full sun, 6+ hours daily",
            "watering": "Daily; loves water — can even grow in shallow water",
            "growTime": "3–4 weeks from seed to harvest",
            "potSize": "Wide shallow container or raised bed",
            "fertilizer": "Nitrogen-rich fertilizer every 2 weeks",
            "soilMix": "Rich loamy soil with high water retention",
            "calendar": [
                {"week": "Week 1", "title": "Sowing", "description": "Broadcast seeds or plant stem cuttings. Water generously."},
                {"week": "Week 2", "title": "Germination", "description": "Seedlings emerge quickly in warm conditions."},
                {"week": "Week 3–4", "title": "Harvest", "description": "Cut top 15cm of stems. New shoots regrow for continued harvest."},
            ],
        },
        "createdAt": datetime.now(timezone.utc),
    },
]


async def seed():
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "homegrow")
    if not uri:
        print("❌  MONGODB_URI not set in .env")
        return

    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    # Drop existing plants
    await db.plants.drop()
    print("🗑  Dropped existing plants collection.")

    result = await db.plants.insert_many(PLANTS)
    print(f"✅  Inserted {len(result.inserted_ids)} plants into '{db_name}.plants':")
    for plant, oid in zip(PLANTS, result.inserted_ids):
        print(f"    {plant['emoji']}  {plant['name']}  →  {oid}")

    client.close()
    print("\nSeeding complete! ✅")


if __name__ == "__main__":
    asyncio.run(seed())
