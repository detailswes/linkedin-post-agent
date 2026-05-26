"""One-shot script to verify the Mongo connection can read and write.

Run from the backend/ folder:

    python scripts/check_mongo.py

Inserts a doc into `_sanity`, reads it back, then drops the collection.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    uri = os.environ["MONGODB_URI"]
    db_name = os.environ.get("MONGODB_DB", "automatic_post_agent")

    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    print(f"connected to db: {db_name}")
    print("collections before:", sorted(await db.list_collection_names()))

    inserted = await db._sanity.insert_one({"hello": "world"})
    print("inserted:", inserted.inserted_id)

    found = await db._sanity.find_one({"_id": inserted.inserted_id})
    print("read back:", found)

    await db._sanity.drop()
    print("dropped _sanity")
    print("collections after:", sorted(await db.list_collection_names()))


if __name__ == "__main__":
    asyncio.run(main())
